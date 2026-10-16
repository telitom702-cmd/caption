
import asyncio
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from plugins.database.database import db


# Original Auto Cleaner-এর একই collection ব্যবহার হবে
cleaner_col = db["auto_cleaner"]

# চলমান স্ক্যান ও অপেক্ষমাণ admin state
OLD_CLEAN_STATE = {}
OLD_CLEAN_TASKS = {}
OLD_CLEAN_PAUSE = {}


def channel_key(chat_id):
    return f"channel:{chat_id}"


async def get_settings():
    settings = await cleaner_col.find_one({"_id": "settings"})

    if not settings:
        settings = {
            "_id": "settings",
            "enabled": True,
            "caption_cleaner": True,
            "remove_texts": ["[CineBari.com]", "MovieBaaz.com"],
        }
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$setOnInsert": settings},
            upsert=True,
        )
        settings = await cleaner_col.find_one({"_id": "settings"})

    return settings


async def get_channels():
    cursor = cleaner_col.find({"type": "channel"}).sort("title", 1)
    return await cursor.to_list(length=None)


def channel_keyboard(chat_id, enabled):
    status = "🟢 ON" if enabled else "🔴 OFF"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{status} — Toggle",
                callback_data=f"oldclean_toggle:{chat_id}",
            ),
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"oldclean_delete:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Channel List",
                callback_data="oldclean_list",
            )
        ],
    ])


def menu_keyboard():
    # এই menu-তে নতুন Channel Cleaner-এর entry points।
    # আপনার পুরোনো /cleaner menu-র বাকি button আগের মতো রাখবেন।
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Add Channel",
                callback_data="oldclean_add",
            ),
            InlineKeyboardButton(
                "📋 Channel List",
                callback_data="oldclean_list",
            ),
        ],
    ])


def clean_caption(caption, remove_texts):
    result = caption or ""

    for text in remove_texts:
        if text:
            result = re.sub(
                re.escape(text),
                "",
                result,
                flags=re.IGNORECASE,
            )

    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", result)

    return result.strip()


def progress_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⏸ Pause",
                callback_data=f"oldclean_pause:{chat_id}",
            ),
            InlineKeyboardButton(
                "▶️ Resume",
                callback_data=f"oldclean_resume:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Progress",
                callback_data=f"oldclean_progress:{chat_id}",
            )
        ],
    ])


async def update_progress_message(
    progress_message,
    chat_id,
    state,
    status,
):
    total = state["total"]
    scanned = state["scanned"]
    cleaned = state["cleaned"]
    failed = state["failed"]

    percent = int(scanned * 100 / total) if total else 100
    filled = int(percent / 10)
    bar = "█" * filled + "░" * (10 - filled)

    text = (
        f"🧹 **Channel Caption Cleaner**\n\n"
        f"📢 Channel: `{chat_id}`\n"
        f"📊 Progress: `{bar}` {percent}%\n\n"
        f"🔎 Scanned: `{scanned}/{total}`\n"
        f"✅ Cleaned: `{cleaned}`\n"
        f"❌ Failed: `{failed}`\n"
        f"⚙️ Status: **{status}**"
    )

    try:
        await progress_message.edit_text(
            text,
            reply_markup=progress_keyboard(chat_id),
        )
    except Exception:
        pass


@Client.on_callback_query(
    filters.regex(r"^oldclean_add$") & filters.user(ADMINS)
)
async def oldclean_add_callback(client, query):
    OLD_CLEAN_STATE[query.from_user.id] = "add"

    await query.answer()
    await query.message.reply_text(
        "➕ চ্যানেলের একটি পোস্ট এখানে ফরওয়ার্ড করুন।\n\n"
        "ফরওয়ার্ড করা পোস্ট থেকে চ্যানেল শনাক্ত করে তালিকায় যোগ করব।\n"
        "বন্ধ করতে /cancel লিখুন।"
    )


@Client.on_callback_query(
    filters.regex(r"^oldclean_list$") & filters.user(ADMINS)
)
async def oldclean_list_callback(client, query):
    await query.answer()

    channels = await get_channels()

    if not channels:
        await query.message.reply_text(
            "📋 কোনো চ্যানেল সেভ করা নেই।\n"
            "Add Channel চাপুন এবং একটি চ্যানেলের পোস্ট ফরওয়ার্ড করুন."
        )
        return

    for channel in channels:
        chat_id = channel["chat_id"]
        enabled = channel.get("enabled", True)
        title = channel.get("title", str(chat_id))

        await query.message.reply_text(
            f"📢 **{title}**\n"
            f"🆔 `{chat_id}`\n"
            f"Status: {'🟢 ON' if enabled else '🔴 OFF'}",
            reply_markup=channel_keyboard(chat_id, enabled),
        )


@Client.on_callback_query(
    filters.regex(r"^oldclean_toggle:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_toggle_callback(client, query):
    await query.answer()

    chat_id = int(query.data.split(":")[1])
    key = channel_key(chat_id)

    channel = await cleaner_col.find_one({"_id": key, "type": "channel"})

    if not channel:
        await query.message.reply_text("এই চ্যানেলটি তালিকায় নেই।")
        return

    new_status = not channel.get("enabled", True)

    await cleaner_col.update_one(
        {"_id": key},
        {"$set": {"enabled": new_status}},
    )

    await query.message.edit_reply_markup(
        reply_markup=channel_keyboard(chat_id, new_status)
    )


@Client.on_callback_query(
    filters.regex(r"^oldclean_delete:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_delete_callback(client, query):
    await query.answer()

    chat_id = int(query.data.split(":")[1])

    await cleaner_col.delete_one({
        "_id": channel_key(chat_id),
        "type": "channel",
    })

    await query.message.edit_text(
        f"✅ `{chat_id}` চ্যানেলটি তালিকা থেকে সরানো হয়েছে।\n"
        "চ্যানেলের আসল পোস্ট ডিলিট করা হয়নি।"
    )


@Client.on_message(
    filters.private
    & filters.user(ADMINS)
    & filters.command("cancel")
)
async def oldclean_cancel(client, message):
    OLD_CLEAN_STATE.pop(message.from_user.id, None)
    await message.reply_text("❎ বাতিল করা হয়েছে।")


@Client.on_message(
    filters.private
    & filters.user(ADMINS)
    & filters.forwarded
)
async def oldclean_forwarded_post(client, message):
    user_id = message.from_user.id
    action = OLD_CLEAN_STATE.get(user_id)

    if action not in ("add", "scan"):
        return

    # Pyrogram 2.x-এ সাধারণ channel forward-এর source
    source = message.forward_from_chat

    if not source or source.type.value != "channel":
        await message.reply_text(
            "❌ চ্যানেলের আসল পোস্টটি source attribution-সহ ফরওয়ার্ড করুন।"
        )
        return

    chat_id = source.id
    title = source.title or str(chat_id)
    key = channel_key(chat_id)

    if action == "add":
        await cleaner_col.update_one(
            {"_id": key},
            {
                "$set": {
                    "type": "channel",
                    "chat_id": chat_id,
                    "title": title,
                    "enabled": True,
                }
            },
            upsert=True,
        )

        OLD_CLEAN_STATE.pop(user_id, None)

        await message.reply_text(
            f"✅ **Channel Saved**\n\n"
            f"📢 {title}\n"
            f"🆔 `{chat_id}`\n"
            f"Status: 🟢 ON",
            reply_markup=channel_keyboard(chat_id, True),
        )
        return

    OLD_CLEAN_STATE.pop(user_id, None)
    await start_old_scan(client, message, chat_id, title)


@Client.on_message(
    filters.private
    & filters.user(ADMINS)
    & filters.command("clean")
)
async def oldclean_command(client, message):
    OLD_CLEAN_STATE[message.from_user.id] = "scan"

    await message.reply_text(
        "🧹 **Old Post Cleaner**\n\n"
        "যে চ্যানেলের পুরোনো পোস্ট পরিষ্কার করতে চান, "
        "সেই চ্যানেলের একটি পোস্ট source attribution-সহ ফরওয়ার্ড করুন।\n\n"
        "শুধু সেভ করা এবং ON থাকা চ্যানেল স্ক্যান হবে।\n"
        "বন্ধ করতে /cancel লিখুন।"
    )


async def start_old_scan(client, message, chat_id, title):
    settings = await get_settings()

    if not settings.get("enabled", True):
        await message.reply_text(
            "❌ মূল Auto Cleaner OFF আছে। আগে /cleaner থেকে ON করুন।"
        )
        return

    channel = await cleaner_col.find_one({
        "_id": channel_key(chat_id),
        "type": "channel",
    })

    if not channel:
        await message.reply_text(
            "❌ এই চ্যানেলটি Channel List-এ নেই। "
            "আগে Add Channel দিয়ে সেভ করুন।"
        )
        return

    if not channel.get("enabled", True):
        await message.reply_text(
            "❌ Channel List-এ এই চ্যানেলটি OFF আছে। আগে ON করুন।"
        )
        return

    if chat_id in OLD_CLEAN_TASKS and not OLD_CLEAN_TASKS[chat_id].done():
        await message.reply_text("⚠️ এই চ্যানেলের স্ক্যান ইতিমধ্যে চলছে।")
        return

    progress_message = await message.reply_text(
        f"🔎 **{title}**\nপোস্টের তালিকা তৈরি হচ্ছে..."
    )

    pause_event = asyncio.Event()
    pause_event.set()
    OLD_CLEAN_PAUSE[chat_id] = pause_event

    task = asyncio.create_task(
        scan_channel_history(
            client,
            chat_id,
            title,
            progress_message,
            settings,
            pause_event,
        )
    )
    OLD_CLEAN_TASKS[chat_id] = task


async def scan_channel_history(
    client,
    chat_id,
    title,
    progress_message,
    settings,
    pause_event,
):
    state = {
        "total": 0,
        "scanned": 0,
        "cleaned": 0,
        "failed": 0,
    }

    try:
        # Telegram history newest-to-oldest দেয়।
        # Message ID ছোট থেকে বড় সাজালে পুরোনো থেকে নতুন হয়।
        message_ids = []

        async for old_message in client.get_chat_history(chat_id):
            message_ids.append(old_message.id)

        message_ids.sort()
        state["total"] = len(message_ids)

        await update_progress_message(
            progress_message, chat_id, state, "Running"
        )

        settings = await get_settings()
        remove_texts = settings.get("remove_texts", [])
        caption_enabled = settings.get("caption_cleaner", True)

        for message_id in message_ids:
            await pause_event.wait()

            # মূল Auto Cleaner OFF হলে পুরোনো স্ক্যানও বন্ধ থাকবে।
            current_settings = await get_settings()
            if not current_settings.get("enabled", True):
                await update_progress_message(
                    progress_message,
                    chat_id,
                    state,
                    "Stopped: Auto Cleaner OFF",
                )
                return

            try:
                post = await client.get_messages(chat_id, message_id)

                if (
                    caption_enabled
                    and post
                    and post.caption
                    and post.media
                ):
                    new_caption = clean_caption(
                        post.caption,
                        remove_texts,
                    )

                    if new_caption != post.caption:
                        await post.edit_caption(new_caption)
                        state["cleaned"] += 1

            except Exception:
                state["failed"] += 1

            state["scanned"] += 1

            if state["scanned"] % 10 == 0:
                await update_progress_message(
                    progress_message,
                    chat_id,
                    state,
                    "Paused" if not pause_event.is_set() else "Running",
                )

        await update_progress_message(
            progress_message,
            chat_id,
            state,
            "Completed",
        )

    except Exception as exc:
        await progress_message.reply_text(
            f"❌ স্ক্যান করতে সমস্যা হয়েছে:\n`{str(exc)[:500]}`"
        )

    finally:
        OLD_CLEAN_TASKS.pop(chat_id, None)
        OLD_CLEAN_PAUSE.pop(chat_id, None)


@Client.on_callback_query(
    filters.regex(r"^oldclean_pause:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_pause_callback(client, query):
    chat_id = int(query.data.split(":")[1])
    event = OLD_CLEAN_PAUSE.get(chat_id)

    if not event:
        await query.answer("কোনো চলমান স্ক্যান নেই।", show_alert=True)
        return

    event.clear()
    await query.answer("স্ক্যান Pause করা হয়েছে।")


@Client.on_callback_query(
    filters.regex(r"^oldclean_resume:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_resume_callback(client, query):
    chat_id = int(query.data.split(":")[1])
    event = OLD_CLEAN_PAUSE.get(chat_id)

    if not event:
        await query.answer("কোনো চলমান স্ক্যান নেই।", show_alert=True)
        return

    event.set()
    await query.answer("স্ক্যান Resume করা হয়েছে।")


@Client.on_callback_query(
    filters.regex(r"^oldclean_progress:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_progress_callback(client, query):
    await query.answer()
    await query.message.reply_text(
        "বর্তমান Progress দেখতে চলমান স্ক্যানের progress message দেখুন।"
    )
