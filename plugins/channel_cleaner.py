import asyncio
import logging
import re

from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    ChatAdminRequired,
    MessageIdInvalid,
    UserNotParticipant,
)
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from info import ADMINS
from plugins.database.database import db

LOGGER = logging.getLogger(__name__)

# auto_cleaner.py-এর একই collection
collection = db.db["auto_cleaner"]

# Admin-এর বর্তমান কাজ
CLEANER_STATE = {}
RUNNING_JOBS = {}  # channel_id -> cancel Event
ZERO_WIDTH = "\u200b"


# -------------------------------------------------------------------
# Settings helpers
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# Origin channel detection
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# Text cleaner
# -------------------------------------------------------------------
def clean_text(text, remove_texts):
    if not text:
        return text

    result = text
    for item in remove_texts:
        if item:
            try:
                result = re.sub(
                    re.escape(item), "", result, flags=re.IGNORECASE
                )
            except re.error:
                # Fallback: literal replace
                result = result.replace(item, "")

    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"^[\s\-_:|]+$", "", result, flags=re.MULTILINE)
    result = "\n".join(
        line.strip() for line in result.splitlines() if line.strip()
    )
    return result.strip()


# -------------------------------------------------------------------
# Keyboard menus
# -------------------------------------------------------------------
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


def cancel_menu():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Stop Cleaning", callback_data="cc_stop")
    ]])


# -------------------------------------------------------------------
# Channel list
# -------------------------------------------------------------------
async def show_channel_list(query):
    settings = await get_settings()
    channels = settings["channels"]

    if not channels:
        try:
            await query.answer(
                "কোনো চ্যানেল যোগ করা হয়নি।", show_alert=True
            )
        except Exception:
            pass
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

    rows.append([InlineKeyboardButton("🔙 Back", callback_data="cc_back")])

    try:
        await query.message.edit_text(
            "📋 **Channel List**\n\n"
            "🟢 ON | 🔴 OFF\n"
            "চ্যানেলের বাটনে চাপ দিয়ে ON/OFF করুন।",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        LOGGER.warning("Could not edit channel list: %s", e)

    try:
        await query.answer()
    except Exception:
        pass


# -------------------------------------------------------------------
# Callback handler
# -------------------------------------------------------------------
@Client.on_callback_query(filters.regex(r"^cc_"))
async def channel_cleaner_callback(client, query):
    if not query.from_user or query.from_user.id not in ADMINS:
        try:
            await query.answer("Admins only!", show_alert=True)
        except Exception:
            pass
        return

    user_id = query.from_user.id
    data = query.data

    # ---- Close ----
    if data == "cc_close":
        CLEANER_STATE.pop(user_id, None)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # ---- Back ----
    if data == "cc_back":
        CLEANER_STATE.pop(user_id, None)
        try:
            await query.message.edit_text(
                "📡 **Channel Cleaner**",
                reply_markup=channel_menu(),
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except MessageNotModified:
            pass
        except Exception:
            pass
        try:
            await query.answer()
        except Exception:
            pass
        return

    # ---- Add channel ----
    if data == "cc_add":
        CLEANER_STATE[user_id] = "add_channel"
        try:
            await query.message.edit_text(
                "➕ যে চ্যানেল যোগ করতে চান, সেই চ্যানেলের একটি পোস্ট "
                "এখানে ফরওয়ার্ড করুন।\n\n"
                "চ্যানেলের পোস্টে বটের প্রয়োজনীয় অ্যাক্সেস থাকতে হবে।",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
                ]]),
            )
        except MessageNotModified:
            pass
        try:
            await query.answer()
        except Exception:
            pass
        return

    # ---- Clean channel ----
    if data == "cc_clean":
        CLEANER_STATE[user_id] = "clean_channel"
        try:
            await query.message.edit_text(
                "🧹 **Clean Channel History**\n\n"
                "যে চ্যানেলের পুরোনো পোস্ট ক্লিন করতে চান, সেই চ্যানেলের "
                "একটি পোস্ট ফরওয়ার্ড করুন।\n\n"
                "বট মূল পোস্ট এডিট করবে; অন্য কোথাও কপি করবে না।",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
                ]]),
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except MessageNotModified:
            pass
        try:
            await query.answer()
        except Exception:
            pass
        return

    # ---- List ----
    if data == "cc_list":
        await show_channel_list(query)
        return

    # ---- Stop cleaning ----
    if data == "cc_stop":
        # সব চলমান job-এর জন্য cancel event সেট করো
        for cid, event in list(RUNNING_JOBS.items()):
            event.set()
        try:
            await query.answer("🛑 স্ক্যান থামানো হচ্ছে...", show_alert=False)
        except Exception:
            pass
        return

    # ---- Toggle ----
    if data.startswith("cc_toggle:"):
        try:
            channel_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("Invalid channel ID", show_alert=True)
            return

        settings = await get_settings()
        channels = settings["channels"]

        found = False
        for item in channels:
            if int(item["id"]) == channel_id:
                item["enabled"] = not item.get("enabled", True)
                found = True
                break

        if found:
            await save_channels(channels)

        await show_channel_list(query)
        return

    # ---- Delete ----
    if data.startswith("cc_delete:"):
        try:
            channel_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("Invalid channel ID", show_alert=True)
            return

        settings = await get_settings()
        channels = [
            item for item in settings["channels"]
            if int(item["id"]) != channel_id
        ]

        await save_channels(channels)
        await show_channel_list(query)
        return


# -------------------------------------------------------------------
# /clean command
# -------------------------------------------------------------------
@Client.on_message(
    filters.private & filters.command("clean") & filters.user(ADMINS)
)
async def clean_command(client, message):
    CLEANER_STATE[message.from_user.id] = "clean_channel"
    await message.reply_text(
        "🧹 যে চ্যানেলের পুরোনো পোস্ট ক্লিন করতে চান, "
        "সেই চ্যানেলের একটি পোস্ট ফরওয়ার্ড করুন।"
    )


# -------------------------------------------------------------------
# Forwarded message handler
# -------------------------------------------------------------------
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
            "❌ মূল চ্যানেল শনাক্ত করা যায়নি। "
            "চ্যানেল থেকে সরাসরি একটি পোস্ট ফরওয়ার্ড করে চেষ্টা করুন।"
        )
        return

    settings = await get_settings()
    channels = settings["channels"]

    existing = next(
        (item for item in channels if int(item["id"]) == int(channel.id)),
        None,
    )

    # ---- Add channel mode ----
    if state == "add_channel":
        if not existing:
            channels.append({
                "id": channel.id,
                "title": channel.title or str(channel.id),
                "enabled": True,
            })
            await save_channels(channels)
            CLEANER_STATE.pop(user_id, None)
            await message.reply_text(
                f"✅ Channel saved: **{channel.title or channel.id}**",
                reply_markup=channel_menu(),
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        else:
            CLEANER_STATE.pop(user_id, None)
            await message.reply_text(
                "ℹ️ এই চ্যানেল আগে থেকেই যোগ করা আছে।",
                reply_markup=channel_menu(),
            )
        return

    # ---- Clean channel mode ----
    # চ্যানেল যোগ না থাকলে প্রথমে যোগ করো
    if not existing:
        channels.append({
            "id": channel.id,
            "title": channel.title or str(channel.id),
            "enabled": True,
        })
        await save_channels(channels)

    CLEANER_STATE.pop(user_id, None)

    await clean_channel_history(
        client, message, channel.id, channel.title or str(channel.id)
    )


# -------------------------------------------------------------------
# Channel history cleaner
# -------------------------------------------------------------------
async def clean_channel_history(client, message, channel_id, title):
    # একই চ্যানেলে আগের কাজ চলছে কিনা চেক
    if channel_id in RUNNING_JOBS:
        await message.reply_text(
            "⚠️ এই চ্যানেলের ক্লিনিং ইতিমধ্যে চলছে।"
        )
        return

    # history_client চেক
    history_client = getattr(client, "history_client", None)
    if history_client is None:
        await message.reply_text(
            "❌ Telegram bot পুরোনো channel history পড়তে পারে না।\n\n"
            "পুরোনো পোস্ট ক্লিন করতে hosting environment-এ "
            "`HISTORY_SESSION` secret হিসেবে একটি Pyrogram user session দিন। "
            "ওই user account-কে channel-এ যুক্ত থাকতে হবে; post edit করবে আগের bot।",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # চ্যানেল enabled কিনা চেক
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

    # Cancel event তৈরি
    cancel_event = asyncio.Event()
    RUNNING_JOBS[channel_id] = cancel_event

    status = await message.reply_text(
        f"🧹 **Channel:** {title}\n"
        "🔎 পুরোনো পোস্ট পরীক্ষা শুরু হচ্ছে...",
        reply_markup=cancel_menu(),
        parse_mode=enums.ParseMode.MARKDOWN,
    )

    scanned = 0
    edited = 0
    skipped = 0
    remove_texts = settings["remove_texts"]
    caption_cleaner = settings.get("caption_cleaner", True)

    try:
        # limit=None: উপলভ্য history সম্পূর্ণ স্ক্যান
        async for post in history_client.get_chat_history(
            channel_id, limit=None
        ):
            # Cancel চেক
            if cancel_event.is_set():
                LOGGER.info(
                    "Cleaning cancelled by user for channel=%s", channel_id
                )
                break

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

            # Empty text fallback
            safe_text = new_text or ZERO_WIDTH

            try:
                if is_caption:
                    await client.edit_message_caption(
                        chat_id=channel_id,
                        message_id=post.id,
                        caption=safe_text,
                    )
                else:
                    await client.edit_message_text(
                        chat_id=channel_id,
                        message_id=post.id,
                        text=safe_text,
                    )

                edited += 1

            except FloodWait as e:
                LOGGER.warning(
                    "FloodWait %ss for channel=%s msg=%s",
                    e.value, channel_id, post.id,
                )
                await asyncio.sleep(e.value + 1)
                # Retry once
                try:
                    if is_caption:
                        await client.edit_message_caption(
                            chat_id=channel_id,
                            message_id=post.id,
                            caption=safe_text,
                        )
                    else:
                        await client.edit_message_text(
                            chat_id=channel_id,
                            message_id=post.id,
                            text=safe_text,
                        )
                    edited += 1
                except Exception as error:
                    skipped += 1
                    LOGGER.warning(
                        "Retry failed channel=%s msg=%s: %s",
                        channel_id, post.id, error,
                    )

            except MessageNotModified:
                # কোনো পরিবর্তন নেই — স্কিপ
                continue

            except (ChatAdminRequired, UserNotParticipant):
                skipped += 1
                LOGGER.warning(
                    "No edit permission in channel=%s", channel_id
                )
                continue

            except MessageIdInvalid:
                skipped += 1
                continue

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
                        "⏳ স্ক্যান চলছে...",
                        reply_markup=cancel_menu(),
                        parse_mode=enums.ParseMode.MARKDOWN,
                    )
                except MessageNotModified:
                    pass
                except Exception:
                    pass

                await asyncio.sleep(0.2)

        # Final status
        final_text = (
            f"✅ **Cleaning Finished**\n\n"
            f"📡 Channel: {title}\n"
            f"🔎 Checked: `{scanned}`\n"
            f"🧹 Cleaned: `{edited}`\n"
            f"⚠️ Failed: `{skipped}`"
        )

        if cancel_event.is_set():
            final_text = (
                f"🛑 **Cleaning Stopped**\n\n"
                f"📡 Channel: {title}\n"
                f"🔎 Checked: `{scaned}`\n"
                f"🧹 Cleaned: `{edited}`\n"
                f"⚠️ Failed: `{skipped}`"
            )

        try:
            await status.edit_text(
                final_text,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    except Exception as error:
        LOGGER.exception("Channel history cleaning failed")
        try:
            await status.edit_text(
                "❌ **History scan বন্ধ হয়েছে।**\n\n"
                f"🔎 Checked: `{scanned}`\n"
                f"🧹 Cleaned: `{edited}`\n"
                f"⚠️ Failed: `{skipped}`\n\n"
                f"Error: `{str(error)[:300]}`",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    finally:
        RUNNING_JOBS.pop(channel_id, None)
