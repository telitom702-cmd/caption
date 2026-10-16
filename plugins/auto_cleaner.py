import asyncio
import logging
import re
from datetime import datetime
from html import escape

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from plugins.database.database import db

LOGGER = logging.getLogger(__name__)

COLLECTION_NAME = "auto_cleaner"
CLEANER_STATE = {}
CHANNEL_STATE = {}
SCAN_TASKS = {}
SCAN_PAUSE = {}
SCAN_PROGRESS = {}

try:
    cleaner_col = db.db[COLLECTION_NAME]
    LOGGER.info("Auto Cleaner collection initialized.")
except Exception:
    LOGGER.exception("Failed to initialize Auto Cleaner collection.")
    raise

DEFAULT_SETTINGS = {
    "_id": "settings",
    "enabled": False,
    "caption_cleaner": True,
    "remove_texts": ["[CineBari.com]", "MovieBaaz.com"],
}


async def get_settings():
    data = await cleaner_col.find_one({"_id": "settings"})
    if not data:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$setOnInsert": DEFAULT_SETTINGS.copy()},
            upsert=True,
        )
        data = await cleaner_col.find_one({"_id": "settings"})
    return data or DEFAULT_SETTINGS.copy()


async def update_settings(data):
    try:
        await cleaner_col.update_one(
            {"_id": "settings"}, {"$set": data}, upsert=True
        )
        return True
    except Exception:
        LOGGER.exception("Failed to update cleaner settings")
        return False


async def is_enabled():
    return bool((await get_settings()).get("enabled", False))


async def get_remove_texts():
    return (await get_settings()).get("remove_texts", [])


async def add_remove_text(text):
    text = text.strip()
    if not text:
        return False
    try:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$addToSet": {"remove_texts": text}},
            upsert=True,
        )
        return True
    except Exception:
        LOGGER.exception("Failed to add remove text")
        return False


async def delete_remove_text(text):
    try:
        result = await cleaner_col.update_one(
            {"_id": "settings"}, {"$pull": {"remove_texts": text}}
        )
        return result.modified_count > 0
    except Exception:
        LOGGER.exception("Failed to delete remove text")
        return False


def clean_text(text, remove_texts):
    if not text:
        return ""
    result = text
    for remove_text in remove_texts:
        if remove_text:
            result = re.sub(re.escape(remove_text), "", result, flags=re.IGNORECASE)
    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"^[\s\-_:|]+$", "", result, flags=re.MULTILINE)
    return "\n".join(line.strip() for line in result.splitlines() if line.strip()).strip()


async def is_processed(chat_id, message_id):
    data = await cleaner_col.find_one({
        "type": "processed",
        "chat_id": int(chat_id),
        "message_id": int(message_id),
    })
    return bool(data)


async def mark_processed(chat_id, message_id):
    await cleaner_col.update_one(
        {
            "type": "processed",
            "chat_id": int(chat_id),
            "message_id": int(message_id),
        },
        {"$set": {
            "type": "processed",
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "processed_at": datetime.utcnow(),
        }},
        upsert=True,
    )


async def process_caption(message):
    if not message.caption:
        return False
    settings = await get_settings()
    remove_texts = settings.get("remove_texts", [])
    if not remove_texts:
        return False
    new_caption = clean_text(message.caption, remove_texts)
    if new_caption == message.caption:
        return False
    try:
        await message.edit_caption(caption=new_caption)
        LOGGER.info("Caption cleaned: chat=%s message=%s", message.chat.id, message.id)
        return True
    except Exception:
        LOGGER.exception("Caption edit failed: chat=%s message=%s", message.chat.id, message.id)
        return False


async def process_message(message):
    settings = await get_settings()
    if not settings.get("enabled", False):
        return
    if await is_processed(message.chat.id, message.id):
        return
    if not (message.video or message.document or message.audio):
        return
    if settings.get("caption_cleaner", True):
        await process_caption(message)
    await mark_processed(message.chat.id, message.id)


@Client.on_message(filters.channel & (filters.video | filters.document | filters.audio))
async def auto_cleaner_channel_handler(client, message):
    try:
        await process_message(message)
    except Exception:
        LOGGER.exception("Auto Cleaner handler error")


async def cleaner_menu():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)
    texts = settings.get("remove_texts", [])
    return (
        f"🧹 <b>Auto Cleaner</b>\n\n"
        f"Status: <b>{'🟢 ON' if enabled else '🔴 OFF'}</b>\n"
        f"Caption Cleaner: <b>{'🟢 ON' if caption_enabled else '🔴 OFF'}</b>\n"
        f"Remove Texts: <b>{len(texts)}</b>"
    )


async def cleaner_keyboard():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Cleaner ON" if enabled else "🔴 Cleaner OFF", callback_data="ac_toggle")],
        [InlineKeyboardButton("🧹 Caption ON" if caption_enabled else "🚫 Caption OFF", callback_data="ac_caption")],
        [
            InlineKeyboardButton("➕ Add Text", callback_data="ac_add"),
            InlineKeyboardButton("➖ Delete Text", callback_data="ac_delete"),
        ],
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="oldclean_add"),
            InlineKeyboardButton("📋 Channel List", callback_data="oldclean_list"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data="ac_refresh"),
         InlineKeyboardButton("❌ Close", callback_data="ac_close")],
    ])


@Client.on_message(filters.private & filters.command("cleaner") & filters.user(ADMINS))
async def cleaner_command(client, message):
    await message.reply_text(
        await cleaner_menu(),
        reply_markup=await cleaner_keyboard(),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^ac_") & filters.user(ADMINS))
async def cleaner_callback(client, query):
    user_id, data = query.from_user.id, query.data

    if data == "ac_close":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_reply_markup(reply_markup=None)
        return

    if data == "ac_toggle":
        settings = await get_settings()
        ok = await update_settings({"enabled": not settings.get("enabled", False)})
        await query.answer("Updated" if ok else "Could not save settings", show_alert=not ok)

    elif data == "ac_caption":
        settings = await get_settings()
        ok = await update_settings({"caption_cleaner": not settings.get("caption_cleaner", True)})
        await query.answer("Updated" if ok else "Could not save settings", show_alert=not ok)

    elif data == "ac_add":
        CLEANER_STATE[user_id] = "add"
        await query.message.reply_text("📝 যে টেক্সট সরাতে চান সেটি পাঠান। /cancel লিখে বাতিল করতে পারবেন।")
        await query.answer()
        return

    elif data == "ac_delete":
        texts = await get_remove_texts()
        if not texts:
            await query.answer("List is empty!", show_alert=True)
            return
        buttons = [
            [InlineKeyboardButton(f"❌ {text[:30]}", callback_data=f"ac_del_{i}")]
            for i, text in enumerate(texts)
        ]
        buttons += [
            [InlineKeyboardButton("🔙 Back", callback_data="ac_refresh")],
            [InlineKeyboardButton("❌ Close", callback_data="ac_close")],
        ]
        await query.message.edit_text("🗑 সরানোর টেক্সট নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(buttons))
        await query.answer()
        return

    elif data.startswith("ac_del_"):
        try:
            index = int(data.rsplit("_", 1)[1])
            texts = await get_remove_texts()
            if index < 0 or index >= len(texts):
                raise ValueError
            ok = await delete_remove_text(texts[index])
            await query.answer("Deleted" if ok else "Could not delete", show_alert=not ok)
        except (ValueError, IndexError):
            await query.answer("Invalid selection", show_alert=True)
            return

    elif data == "ac_refresh":
        await query.answer()

    try:
        await query.message.edit_text(
            await cleaner_menu(),
            reply_markup=await cleaner_keyboard(),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass


@Client.on_message(
    filters.private & filters.text & filters.user(ADMINS)
    & ~filters.command(["cancel", "start", "cleaner", "clean", "id", "stats"])
)
async def cleaner_text_input(client, message):
    user_id = message.from_user.id
    value = (message.text or "").strip()

    if CLEANER_STATE.get(user_id) == "add":
        if not value:
            await message.reply_text("❌ Empty text is not allowed.")
            return
        if not await add_remove_text(value):
            await message.reply_text("❌ টেক্সট সেভ করা যায়নি।")
            return
        CLEANER_STATE.pop(user_id, None)
        await message.reply_text(f"✅ Added: <code>{escape(value)}</code>", parse_mode=enums.ParseMode.HTML)
        await message.reply_text(await cleaner_menu(), reply_markup=await cleaner_keyboard(), parse_mode=enums.ParseMode.HTML)
        return

    if CHANNEL_STATE.get(user_id) == "add_id":
        try:
            chat_id = int(value)
            chat = await client.get_chat(chat_id)
            if chat.type != enums.ChatType.CHANNEL:
                await message.reply_text("❌ এটি চ্যানেল ID নয়। সঠিক channel ID দিন।")
                return
        except Exception:
            await message.reply_text("❌ চ্যানেল পাওয়া যায়নি। ID সঠিক কি না এবং বটের অ্যাক্সেস আছে কি না দেখুন।")
            return

        key = f"channel:{chat.id}"
        await cleaner_col.update_one(
            {"_id": key},
            {"$set": {
                "type": "channel",
                "chat_id": chat.id,
                "title": chat.title or str(chat.id),
                "enabled": True,
            }},
            upsert=True,
        )
        CHANNEL_STATE.pop(user_id, None)
        await message.reply_text(
            f"✅ চ্যানেল সেভ হয়েছে\n📢 {escape(chat.title or str(chat.id))}\n🆔 <code>{chat.id}</code>",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=channel_keyboard(chat.id, True),
        )


@Client.on_message(filters.private & filters.command("cancel") & filters.user(ADMINS))
async def cancel_states(client, message):
    CLEANER_STATE.pop(message.from_user.id, None)
    CHANNEL_STATE.pop(message.from_user.id, None)
    await message.reply_text("❎ বাতিল করা হয়েছে।")


def channel_keyboard(chat_id, enabled):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 ON" if enabled else "🔴 OFF",
                callback_data=f"oldclean_toggle:{chat_id}",
            ),
            InlineKeyboardButton("🗑 Delete", callback_data=f"oldclean_delete:{chat_id}"),
        ],
        [InlineKeyboardButton("⬅️ Channel List", callback_data="oldclean_list")],
    ])


@Client.on_callback_query(filters.regex(r"^oldclean_add$") & filters.user(ADMINS))
async def oldclean_add(client, query):
    CHANNEL_STATE[query.from_user.id] = "add_id"
    await query.answer()
    await query.message.reply_text("➕ চ্যানেলের numeric ID পাঠান (যেমন: -1001234567890)।\nবাতিল করতে /cancel লিখুন।")


@Client.on_callback_query(filters.regex(r"^oldclean_list$") & filters.user(ADMINS))
async def oldclean_list(client, query):
    await query.answer()
    cursor = cleaner_col.find({"type": "channel"}).sort("title", 1)
    channels = await cursor.to_list(length=None)
    if not channels:
        await query.message.reply_text("📋 কোনো চ্যানেল সেভ নেই। Add Channel দিয়ে আগে ID যোগ করুন।")
        return
    for channel in channels:
        chat_id = int(channel["chat_id"])
        enabled = channel.get("enabled", True)
        await query.message.reply_text(
            f"📢 <b>{escape(channel.get('title', str(chat_id)))}</b>\n"
            f"🆔 <code>{chat_id}</code>\n"
            f"Status: {'🟢 ON' if enabled else '🔴 OFF'}",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=channel_keyboard(chat_id, enabled),
        )


@Client.on_callback_query(filters.regex(r"^oldclean_toggle:-?\d+$") & filters.user(ADMINS))
async def oldclean_toggle(client, query):
    chat_id = int(query.data.split(":")[1])
    key = f"channel:{chat_id}"
    channel = await cleaner_col.find_one({"_id": key, "type": "channel"})
    if not channel:
        await query.answer("চ্যানেল তালিকায় নেই", show_alert=True)
        return
    enabled = not channel.get("enabled", True)
    await cleaner_col.update_one({"_id": key}, {"$set": {"enabled": enabled}})
    await query.message.edit_reply_markup(reply_markup=channel_keyboard(chat_id, enabled))
    await query.answer("Updated")


@Client.on_callback_query(filters.regex(r"^oldclean_delete:-?\d+$") & filters.user(ADMINS))
async def oldclean_delete(client, query):
    chat_id = int(query.data.split(":")[1])
    await cleaner_col.delete_one({"_id": f"channel:{chat_id}", "type": "channel"})
    await query.message.edit_text("✅ চ্যানেলটি শুধু তালিকা থেকে সরানো হয়েছে। আসল পোস্ট ডিলিট হয়নি।")
    await query.answer("Deleted")


@Client.on_message(filters.private & filters.command("clean") & filters.user(ADMINS))
async def oldclean_command(client, message):
    CHANNEL_STATE[message.from_user.id] = "await_forward"
    await message.reply_text(
        "🧹 যে সেভ করা চ্যানেল পরিষ্কার করতে চান, সেই চ্যানেলের একটি পোস্ট source attribution-সহ ফরওয়ার্ড করুন।\n"
        "চ্যানেলটি আগে Add Channel দিয়ে ID-সহ সেভ করা এবং ON থাকা বাধ্যতামূলক।\n"
        "/cancel লিখে বাতিল করতে পারবেন।"
    )


@Client.on_message(filters.private & filters.forwarded & filters.user(ADMINS))
async def oldclean_forwarded(client, message):
    user_id = message.from_user.id
    if CHANNEL_STATE.get(user_id) != "await_forward":
        return

    source = getattr(message, "forward_from_chat", None)
    if not source or source.type != enums.ChatType.CHANNEL:
        await message.reply_text("❌ source attribution-সহ চ্যানেলের পোস্ট ফরওয়ার্ড করুন।")
        return

    chat_id = source.id
    channel = await cleaner_col.find_one({"_id": f"channel:{chat_id}", "type": "channel"})
    if not channel:
        await message.reply_text("❌ এই চ্যানেল সেভ করা নেই। আগে /cleaner → Add Channel দিয়ে ID যোগ করুন।")
        return
    if not channel.get("enabled", True):
        await message.reply_text("❌ Channel List-এ এই চ্যানেল OFF আছে। আগে ON করুন।")
        return

    settings = await get_settings()
    if not settings.get("enabled", False):
        await message.reply_text("❌ মূল Auto Cleaner OFF আছে। /cleaner থেকে ON করুন।")
        return

    CHANNEL_STATE.pop(user_id, None)
    if chat_id in SCAN_TASKS and not SCAN_TASKS[chat_id].done():
        await message.reply_text("⚠️ এই চ্যানেলের স্ক্যান ইতিমধ্যে চলছে।")
        return

    status_message = await message.reply_text("🔎 চ্যানেলের পোস্ট তালিকা তৈরি হচ্ছে...")
    pause_event = asyncio.Event()
    pause_event.set()
    SCAN_PAUSE[chat_id] = pause_event
    SCAN_PROGRESS[chat_id] = {"total": 0, "scanned": 0, "cleaned": 0, "failed": 0, "message": status_message}
    SCAN_TASKS[chat_id] = asyncio.create_task(
        scan_old_posts(client, chat_id, status_message, pause_event)
    )


async def render_scan_progress(chat_id, status="Running"):
    state = SCAN_PROGRESS.get(chat_id)
    if not state:
        return
    total = state["total"]
    scanned = state["scanned"]
    percent = int(scanned * 100 / total) if total else 0
    filled = min(10, percent // 10)
    bar = "█" * filled + "░" * (10 - filled)
    text = (
        f"🧹 <b>Old Post Cleaner</b>\n\n"
        f"📊 <code>{bar}</code> {percent}%\n"
        f"🔎 Scanned: <code>{scanned}/{total}</code>\n"
        f"✅ Cleaned: <code>{state['cleaned']}</code>\n"
        f"❌ Failed: <code>{state['failed']}</code>\n"
        f"⚙️ Status: <b>{status}</b>"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸ Pause", callback_data=f"oldclean_pause:{chat_id}"),
            InlineKeyboardButton("▶️ Resume", callback_data=f"oldclean_resume:{chat_id}"),
        ],
        [InlineKeyboardButton("🔄 Progress", callback_data=f"oldclean_progress:{chat_id}")],
    ])
    try:
        await state["message"].edit_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=keyboard)
    except Exception:
        pass


async def scan_old_posts(client, chat_id, status_message, pause_event):
    try:
        ids = []
        async for post in client.get_chat_history(chat_id):
            ids.append(post.id)
        ids.sort()
        state = SCAN_PROGRESS[chat_id]
        state["total"] = len(ids)
        await render_scan_progress(chat_id)

        for message_id in ids:
            await pause_event.wait()
            settings = await get_settings()
            channel = await cleaner_col.find_one({"_id": f"channel:{chat_id}", "type": "channel"})
            if not settings.get("enabled", False) or not channel or not channel.get("enabled", True):
                await render_scan_progress(chat_id, "Stopped: Cleaner/Channel OFF")
                return

            try:
                post = await client.get_messages(chat_id, message_id)
                if post and (post.video or post.document or post.audio):
                    settings = await get_settings()
                    if settings.get("caption_cleaner", True) and post.caption:
                        new_caption = clean_text(post.caption, settings.get("remove_texts", []))
                        if new_caption != post.caption:
                            await post.edit_caption(caption=new_caption)
                            state["cleaned"] += 1
            except Exception:
                state["failed"] += 1
                LOGGER.exception("Old scan failed: chat=%s message=%s", chat_id, message_id)

            state["scanned"] += 1
            if state["scanned"] % 10 == 0 or state["scanned"] == state["total"]:
                await render_scan_progress(chat_id, "Paused" if not pause_event.is_set() else "Running")

        await render_scan_progress(chat_id, "Completed")
    except Exception:
        LOGGER.exception("Old post scan failed for %s", chat_id)
        try:
            await status_message.reply_text("❌ স্ক্যান ব্যর্থ হয়েছে। বটের চ্যানেল অ্যাক্সেস ও edit permission পরীক্ষা করুন।")
        except Exception:
            pass
    finally:
        SCAN_TASKS.pop(chat_id, None)
        SCAN_PAUSE.pop(chat_id, None)


@Client.on_callback_query(filters.regex(r"^oldclean_pause:-?\d+$") & filters.user(ADMINS))
async def oldclean_pause(client, query):
    chat_id = int(query.data.split(":")[1])
    event = SCAN_PAUSE.get(chat_id)
    if not event:
        await query.answer("চলমান স্ক্যান নেই।", show_alert=True)
        return
    event.clear()
    await query.answer("Paused")


@Client.on_callback_query(filters.regex(r"^oldclean_resume:-?\d+$") & filters.user(ADMINS))
async def oldclean_resume(client, query):
    chat_id = int(query.data.split(":")[1])
    event = SCAN_PAUSE.get(chat_id)
    if not event:
        await query.answer("চলমান স্ক্যান নেই।", show_alert=True)
        return
    event.set()
    await query.answer("Resumed")


@Client.on_callback_query(filters.regex(r"^oldclean_progress:-?\d+$") & filters.user(ADMINS))
async def oldclean_progress(client, query):
    chat_id = int(query.data.split(":")[1])
    await query.answer()
    await render_scan_progress(chat_id, "Paused" if chat_id in SCAN_PAUSE and not SCAN_PAUSE[chat_id].is_set() else "Running")
