
import asyncio
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS
from plugins.database.database import db

LOGGER = logging.getLogger(__name__)

# auto_cleaner.py-এর একই collection
collection = db.db["auto_cleaner"]

# Admin-এর বর্তমান কাজ
CLEANER_STATE = {}
RUNNING_JOBS = set()


async def get_settings():
    data = await collection.find_one({"_id": "settings"}) or {}
    return {
        "enabled": data.get("enabled", False),
        "caption_cleaner": data.get("caption_cleaner", True),
        "remove_texts": data.get("remove_texts", []),
        "channels": data.get("channels", []),
    }


async def save_channels(channels):
    await collection.update_one(
        {"_id": "settings"},
        {"$set": {"channels": channels}},
        upsert=True,
    )


def get_origin_channel(message):
    """Forward করা পোস্টের মূল channel শনাক্ত করে।"""
    chat = getattr(message, "forward_from_chat", None)
    if chat and chat.type == enums.ChatType.CHANNEL:
        return chat

    origin = getattr(message, "forward_origin", None)
    origin_chat = getattr(origin, "chat", None) if origin else None

    if origin_chat and origin_chat.type == enums.ChatType.CHANNEL:
        return origin_chat

    return None


def clean_text(text, remove_texts):
    if not text:
        return text

    import re

    result = text
    for item in remove_texts:
        if item:
            result = re.sub(
                re.escape(item), "", result, flags=re.IGNORECASE
            )

    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"^[\s\-_:|]+$", "", result, flags=re.MULTILINE)
    result = "\n".join(
        line.strip() for line in result.splitlines() if line.strip()
    )
    return result.strip()


def channel_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="cc_add"),
            InlineKeyboardButton("📋 Channel List", callback_data="cc_list"),
        ],
        [
            InlineKeyboardButton(
                "🧹 Clean Channel History", callback_data="cc_clean"
            )
        ],
        [
            InlineKeyboardButton("🔙 Back to Cleaner", callback_data="cc_back"),
            InlineKeyboardButton("❌ Close", callback_data="cc_close"),
        ],
    ])


async def show_channel_list(query):
    settings = await get_settings()
    channels = settings["channels"]

    if not channels:
        await query.answer("কোনো চ্যানেল যোগ করা হয়নি।", show_alert=True)
        return

    rows = []

    for item in channels:
        channel_id = item["id"]
        title = item.get("title") or str(channel_id)
        enabled = item.get("enabled", True)

        rows.append([
            InlineKeyboardButton(
                f"{'🟢' if enabled else '🔴'} {title[:24]}",
                callback_data=f"cc_toggle:{channel_id}",
            ),
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"cc_delete:{channel_id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton("🔙 Back", callback_data="cc_back")
    ])

    await query.message.edit_text(
        "📋 **Channel List**\n\n"
        "🟢 ON | 🔴 OFF\n"
        "চ্যানেলের বাটনে চাপ দিয়ে ON/OFF করুন।",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    await query.answer()


@Client.on_callback_query(filters.regex(r"^cc_"))
async def channel_cleaner_callback(client, query):
    if not query.from_user or query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return

    user_id = query.from_user.id
    data = query.data

    if data == "cc_close":
        CLEANER_STATE.pop(user_id, None)
        await query.message.delete()
        return

    if data == "cc_back":
        CLEANER_STATE.pop(user_id, None)
        await query.message.edit_text(
            "📡 **Channel Cleaner**",
            reply_markup=channel_menu(),
        )
        await query.answer()
        return

    if data == "cc_add":
        CLEANER_STATE[user_id] = "add_channel"
        await query.message.edit_text(
            "➕ যে চ্যানেল যোগ করতে চান, সেই চ্যানেলের একটি পোস্ট "
            "এখানে ফরওয়ার্ড করুন।\n\n"
            "চ্যানেলের পোস্টে বটের প্রয়োজনীয় অ্যাক্সেস থাকতে হবে।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
            ]]),
        )
        await query.answer()
        return

    if data == "cc_clean":
        CLEANER_STATE[user_id] = "clean_channel"
        await query.message.edit_text(
            "🧹 **Clean Channel History**\n\n"
            "যে চ্যানেলের পুরোনো পোস্ট ক্লিন করতে চান, সেই চ্যানেলের "
            "একটি পোস্ট ফরওয়ার্ড করুন।\n\n"
            "বট মূল পোস্ট এডিট করবে; অন্য কোথাও কপি করবে না।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
            ]]),
        )
        await query.answer()
        return

    if data == "cc_list":
        await show_channel_list(query)
        return

    if data.startswith("cc_toggle:"):
        channel_id = int(data.split(":", 1)[1])
        settings = await get_settings()
        channels = settings["channels"]

        for item in channels:
            if int(item["id"]) == channel_id:
                item["enabled"] = not item.get("enabled", True)
                break

        await save_channels(channels)
        await show_channel_list(query)
        return

    if data.startswith("cc_delete:"):
        channel_id = int(data.split(":", 1)[1])
        settings = await get_settings()
        channels = [
            item for item in settings["channels"]
            if int(item["id"]) != channel_id
        ]

        await save_channels(channels)
        await show_channel_list(query)
        return


@Client.on_message(
    filters.private & filters.command("clean") & filters.user(ADMINS)
)
async def clean_command(client, message):
    CLEANER_STATE[message.from_user.id] = "clean_channel"
    await message.reply_text(
        "🧹 যে চ্যানেলের পুরোনো পোস্ট ক্লিন করতে চান, "
        "সেই চ্যানেলের একটি পোস্ট ফরওয়ার্ড করুন।"
    )


@Client.on_message(
    filters.private & filters.forwarded & filters.user(ADMINS)
)
async def channel_forward_handler(client, message):
    if not message.from_user:
        return

    user_id = message.from_user.id
    state = CLEANER_STATE.get(user_id)

    if state not in ("add_channel", "clean_channel"):
        return

    channel = get_origin_channel(message)

    if not channel:
        await message.reply_text(
            "❌ মূল চ্যানেল শনাক্ত করা যায়নি। "
            "চ্যানেল থেকে সরাসরি একটি পোস্ট ফরওয়ার্ড করে চেষ্টা করুন।"
        )
        return

    settings = await get_settings()
    channels = settings["channels"]

    existing = next(
        (item for item in channels if int(item["id"]) == int(channel.id)),
        None,
    )

    if not existing:
        channels.append({
            "id": channel.id,
            "title": channel.title or str(channel.id),
            "enabled": True,
        })
        await save_channels(channels)

    elif state == "add_channel":
        await message.reply_text("ℹ️ এই চ্যানেল আগে থেকেই যোগ করা আছে।")

    CLEANER_STATE.pop(user_id, None)

    if state == "add_channel":
        await message.reply_text(
            f"✅ Channel saved: {channel.title or channel.id}",
            reply_markup=channel_menu(),
        )
        return

    # Clean command: চ্যানেলের পুরোনো পোস্ট স্ক্যান করা
    await clean_channel_history(
        client, message, channel.id, channel.title or str(channel.id)
    )


async def clean_channel_history(client, message, channel_id, title):
    if channel_id in RUNNING_JOBS:
        await message.reply_text("⚠️ এই চ্যানেলের ক্লিনিং চলছে।")
        return

    settings = await get_settings()
    channel_entry = next(
        (
            item for item in settings["channels"]
            if int(item["id"]) == int(channel_id)
        ),
        None,
    )

    if channel_entry and not channel_entry.get("enabled", True):
        await message.reply_text(
            "🔴 এই চ্যানেলটি OFF করা আছে। Channel List থেকে ON করুন।"
        )
        return

    RUNNING_JOBS.add(channel_id)

    status = await message.reply_text(
        f"🧹 **Channel:** {title}\n"
        "🔎 পুরোনো পোস্ট পরীক্ষা শুরু হচ্ছে..."
    )

    scanned = 0
    edited = 0
    skipped = 0
    remove_texts = settings["remove_texts"]
    caption_cleaner = settings.get("caption_cleaner", True)

    try:
        # limit=0: উপলভ্য history সম্পূর্ণ স্ক্যান করার চেষ্টা
        async for post in client.get_chat_history(channel_id, limit=0):
            scanned += 1

            # পোস্টের টেক্সট অথবা ক্যাপশন
            old_text = post.text
            is_caption = bool(post.caption)

            if is_caption:
                old_text = post.caption
                if not caption_cleaner:
                    continue

            if not old_text:
                continue

            new_text = clean_text(old_text, remove_texts)

            if new_text == old_text:
                continue

            try:
                if is_caption:
                    await client.edit_message_caption(
                        chat_id=channel_id,
                        message_id=post.id,
                        caption=new_text or None,
                    )
                else:
                    await client.edit_message_text(
                        chat_id=channel_id,
                        message_id=post.id,
                        text=new_text or " ",
                    )

                edited += 1

            except Exception as error:
                skipped += 1
                LOGGER.warning(
                    "Could not edit channel=%s message=%s: %s",
                    channel_id, post.id, error,
                )

            # প্রতি 20টি পোস্টে progress update
            if scanned % 20 == 0:
                try:
                    await status.edit_text(
                        f"🧹 **Channel:** {title}\n\n"
                        f"🔎 Checked: `{scanned}`\n"
                        f"✅ Cleaned: `{edited}`\n"
                        f"⚠️ Failed: `{skipped}`\n\n"
                        "⏳ স্ক্যান চলছে..."
                    )
                except Exception:
                    pass

                await asyncio.sleep(0.2)

        await status.edit_text(
            f"✅ **Cleaning Finished**\n\n"
            f"📡 Channel: {title}\n"
            f"🔎 Checked: `{scanned}`\n"
            f"🧹 Cleaned: `{edited}`\n"
            f"⚠️ Failed: `{skipped}`"
        )

    except Exception as error:
        LOGGER.exception("Channel history cleaning failed")
        try:
            await status.edit_text(
                "❌ **History scan বন্ধ হয়েছে।**\n\n"
                f"🔎 Checked: `{scanned}`\n"
                f"🧹 Cleaned: `{edited}`\n"
                f"⚠️ Failed: `{skipped}`\n\n"
                f"Error: `{str(error)[:300]}`"
            )
        except Exception:
            pass

    finally:
        RUNNING_JOBS.discard(channel_id)
