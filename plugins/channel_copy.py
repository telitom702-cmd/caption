# ©️ DramaZ.botz | @ 👨‍💻 Developer: Omar.Z.botz | NT_BOT_CHANNEL
#
# Advanced Telegram Channel Copy System
# Source Channel -> Target Channel
# COPY, NOT FORWARD

import asyncio
import logging
import re
from datetime import datetime, timezone

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from pyrogram.errors import (
    FloodWait,
    RPCError,
)

from info import ADMINS
from plugins.database.database import db

# ক্লিনার ফাইল থেকে state ইম্পোর্ট করা হচ্ছে যাতে কনফ্লিক্ট না হয়
try:
    from plugins.autocleaner import CLEANER_STATE
except ImportError:
    CLEANER_STATE = {}

# ============================================================
# LOGGER
# ============================================================
LOGGER = logging.getLogger(__name__)

# ============================================================
# DATABASE
# ============================================================
COLLECTION_NAME = "channel_copy"
copy_col = db.db[COLLECTION_NAME]

# সেটিংস আইডি পরিবর্তন করা হলো যাতে ডাটাবেসে মিক্স না হয়
SETTINGS_ID = "copy_settings"

# নাম পরিবর্তন করা হলো (DEFAULT_SETTINGS -> COPY_DEFAULT_SETTINGS)
COPY_DEFAULT_SETTINGS = {
    "_id": SETTINGS_ID,
    "enabled": False,
    "source_chat": None,
    "target_chat": None,
    "source_enabled": True,   # সোর্স চ্যানেল অন/অফ এর জন্য
    "target_enabled": True,   # টার্গেট চ্যানেল অন/অফ এর জন্য
    "language": "both",
    "retry_delay": 30,
    "created_at": None,
    "updated_at": None,
}

COPY_LOCK = asyncio.Lock()
STOP_EVENT = asyncio.Event()
RUNNING_TASK = None
ADMIN_STATE = {}

# ============================================================
# DATABASE SETTINGS (নাম পরিবর্তন করা হয়েছে)
# ============================================================
async def get_copy_settings():
    try:
        data = await copy_col.find_one({"_id": SETTINGS_ID})
        if not data:
            data = COPY_DEFAULT_SETTINGS.copy()
            now = datetime.now(timezone.utc)
            data["created_at"] = now
            data["updated_at"] = now
            await copy_col.insert_one(data.copy())
        return data
    except Exception as e:
        LOGGER.exception("get_copy_settings error: %s", e)
        return COPY_DEFAULT_SETTINGS.copy()

async def update_copy_settings(data):
    try:
        data = dict(data)
        data["updated_at"] = datetime.now(timezone.utc)
        await copy_col.update_one(
            {"_id": SETTINGS_ID},
            {"$set": data},
            upsert=True,
        )
        return True
    except Exception as e:
        LOGGER.exception("update_copy_settings error: %s", e)
        return False

# ============================================================
# CLEAR DATABASE SYSTEM
# ============================================================
async def clear_copy_database():
    try:
        await copy_col.delete_many({"type": "copy_job"})
        await copy_col.delete_many({"type": "target_file"})
        return True
    except Exception as e:
        LOGGER.exception("Clear database error: %s", e)
        return False

# ============================================================
# MEDIA HELPERS
# ============================================================
def get_media(message):
    if message.photo: return "photo", message.photo
    if message.video: return "video", message.video
    if message.document: return "document", message.document
    if message.audio: return "audio", message.audio
    if message.animation: return "animation", message.animation
    if message.voice: return "voice", message.voice
    return None, None

def get_file_unique_id(message):
    _, media = get_media(message)
    if not media: return None
    return getattr(media, "file_unique_id", None)

def get_file_name(message):
    if message.document: return message.document.file_name or ""
    if message.video: return message.video.file_name or ""
    if message.audio: return message.audio.file_name or ""
    if message.animation: return message.animation.file_name or ""
    if message.photo: return "photo"
    return ""

def get_file_size(message):
    _, media = get_media(message)
    if not media: return 0
    return int(getattr(media, "file_size", 0) or 0)

# ============================================================
# LANGUAGE DETECTION
# ============================================================
BANGLA_RE = re.compile(r"[\u0980-\u09FF]")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

def detect_language(message):
    try:
        filename = get_file_name(message)
        caption = message.caption or ""
        text = f"{filename}\n{caption}"
        if not text.strip(): return "unknown"
        has_bangla = bool(BANGLA_RE.search(text))
        has_hindi = bool(DEVANAGARI_RE.search(text))
        if has_bangla and has_hindi: return "mixed"
        if has_bangla: return "bangla"
        if has_hindi: return "hindi"
        return "unknown"
    except Exception as e:
        LOGGER.warning("Language detection failed: %s", e)
        return "unknown"

def language_allowed(message, mode):
    try:
        mode = str(mode or "both").lower()
        detected = detect_language(message)
        if mode == "both": return True
        if mode == "hindi": return detected in ("hindi", "mixed")
        if mode == "bangla": return detected in ("bangla", "mixed")
        return True
    except Exception as e:
        LOGGER.warning("language_allowed error: %s", e)
        return True

# ============================================================
# FILENAME NORMALIZATION
# ============================================================
def normalize_filename(name):
    if not name: return ""
    try:
        name = name.lower()
        name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|mp3|m4a|aac|flac|zip|rar|7z)$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"[\W_]+", "", name, flags=re.UNICODE)
        return name.strip()
    except Exception:
        return str(name).lower().strip()

def make_job_key(message):
    unique_id = get_file_unique_id(message)
    if unique_id: return f"file:{unique_id}"
    return f"message:{message.chat.id}:{message.id}"

# ============================================================
# TARGET DUPLICATE CHECK & MARK
# ============================================================
async def target_file_exists(message):
    unique_id = get_file_unique_id(message)
    if unique_id:
        found = await copy_col.find_one({"type": "target_file", "file_unique_id": unique_id})
        if found: return True
    filename = normalize_filename(get_file_name(message))
    size = get_file_size(message)
    if filename and size:
        found = await copy_col.find_one({"type": "target_file", "normalized_filename": filename, "file_size": size})
        if found: return True
    return False

async def mark_target_file(message, target_message_id):
    try:
        unique_id = get_file_unique_id(message)
        filename = get_file_name(message)
        await copy_col.update_one(
            {"type": "target_file", "target_message_id": int(target_message_id)},
            {"$set": {
                "type": "target_file",
                "file_unique_id": unique_id,
                "normalized_filename": normalize_filename(filename),
                "filename": filename,
                "file_size": get_file_size(message),
                "target_message_id": int(target_message_id),
                "indexed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as e:
        LOGGER.exception("mark_target_file error: %s", e)

# ============================================================
# JOB FUNCTIONS
# ============================================================
async def get_job(message):
    return await copy_col.find_one({"type": "copy_job", "job_key": make_job_key(message)})

async def create_job(message):
    key = make_job_key(message)
    existing = await copy_col.find_one({"type": "copy_job", "job_key": key})
    if existing: return existing
    job = {
        "type": "copy_job", "job_key": key,
        "source_chat": int(message.chat.id), "source_message_id": int(message.id),
        "file_unique_id": get_file_unique_id(message), "filename": get_file_name(message),
        "normalized_filename": normalize_filename(get_file_name(message)),
        "file_size": get_file_size(message), "language": detect_language(message),
        "status": "pending", "retry_count": 0, "last_error": None,
        "target_message_id": None, "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    try:
        await copy_col.insert_one(job)
        return job
    except Exception:
        return await get_job(message)

async def update_job(message, data):
    data = dict(data)
    data["updated_at"] = datetime.now(timezone.utc)
    await copy_col.update_one(
        {"type": "copy_job", "job_key": make_job_key(message)},
        {"$set": data}, upsert=True,
    )

# ============================================================
# COPY ONE MESSAGE
# ============================================================
async def copy_one_message(client, message):
    settings = await get_copy_settings()
    target_chat = settings.get("target_chat")
    if not target_chat: raise RuntimeError("Target channel is not configured.")
    
    # চ্যানেল অফ থাকলে কপি করবে না এবং জব সেভও করবে না
    if not settings.get("source_enabled", True) or not settings.get("target_enabled", True):
        return "skipped_disabled"
        
    if not language_allowed(message, settings.get("language", "both")):
        await create_job(message)
        await update_job(message, {"status": "skipped_language"})
        return "skipped_language"

    if await target_file_exists(message):
        await create_job(message)
        await update_job(message, {"status": "skipped_target_duplicate"})
        return "skipped_target_duplicate"

    await create_job(message)
    await update_job(message, {"status": "processing", "last_error": None})

    try:
        copied = await client.copy_message(chat_id=target_chat, from_chat_id=message.chat.id, message_id=message.id)
        target_message_id = copied.id if copied else None
        await update_job(message, {"status": "copied", "target_message_id": target_message_id, "last_error": None, "copied_at": datetime.now(timezone.utc)})
        if target_message_id: await mark_target_file(message, target_message_id)
        LOGGER.info("Copied: %s/%s -> %s/%s", message.chat.id, message.id, target_chat, target_message_id)
        return "copied"
    except FloodWait as e:
        job = await get_job(message)
        retry_count = int(job.get("retry_count", 0) if job else 0)
        await update_job(message, {"status": "retry", "retry_count": retry_count + 1, "last_error": f"FloodWait: {e.value}"})
        raise
    except Exception as e:
        job = await get_job(message)
        retry_count = int(job.get("retry_count", 0) if job else 0)
        await update_job(message, {"status": "retry", "retry_count": retry_count + 1, "last_error": str(e)[:2000]})
        raise

# ============================================================
# INDEX TARGET CHANNEL
# ============================================================
async def index_target_channel(client):
    settings = await get_copy_settings()
    target_chat = settings.get("target_chat")
    if not target_chat: raise RuntimeError("Target channel is not configured.")
    count = 0
    async for message in client.get_chat_history(target_chat):
        if STOP_EVENT.is_set(): break
        if not get_media(message)[0]: continue
        await mark_target_file(message, message.id)
        count += 1
    LOGGER.info("Target indexed: %s", count)
    return count

# ============================================================
# OLD SOURCE COPY
# ============================================================
async def copy_old_posts(client):
    settings = await get_copy_settings()
    source_chat = settings.get("source_chat")
    if not source_chat: raise RuntimeError("Source channel is not configured.")
    
    # চ্যানেল অফ থাকলে পুরোনো ফাইল কপি করার লুপে ঢুকবেই না
    if not settings.get("source_enabled", True) or not settings.get("target_enabled", True):
        LOGGER.info("Copy skipped because source or target is disabled.")
        return
        
    total = copied = skipped = errors = 0
    async for message in client.get_chat_history(source_chat):
        if STOP_EVENT.is_set(): break
        if not get_media(message)[0]: continue
        total += 1
        try:
            result = await copy_one_message(client, message)
            if result == "copied": copied += 1
            else: skipped += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            errors += 1
            LOGGER.error("Copy failed; kept in retry queue | message=%s | %s", message.id, e)
        await asyncio.sleep(0.5)
    LOGGER.info("Old copy finished | total=%s copied=%s skipped=%s errors=%s", total, copied, skipped, errors)

# ============================================================
# RETRY QUEUE
# ============================================================
async def process_retry_queue(client):
    settings = await get_copy_settings()
    source_chat = settings.get("source_chat")
    if not source_chat: return
    cursor = copy_col.find({"type": "copy_job", "status": "retry"}).sort("updated_at", 1).limit(50)
    async for job in cursor:
        if STOP_EVENT.is_set(): return
        message_id = job.get("source_message_id")
        try:
            message = await client.get_messages(source_chat, message_id)
            if not message: continue
            try: await copy_one_message(client, message)
            except FloodWait as e: await asyncio.sleep(e.value)
            except Exception as e: LOGGER.warning("Retry failed: %s | %s", message_id, e)
            await asyncio.sleep(int(settings.get("retry_delay", 30)))
        except Exception as e:
            LOGGER.warning("Retry get message failed: %s", e)

# ============================================================
# FULL OLD COPY RUNNER
# ============================================================
async def run_copy_system(client):
    global RUNNING_TASK
    if COPY_LOCK.locked(): return
    async with COPY_LOCK:
        try:
            settings = await get_copy_settings()
            if not settings.get("enabled", False): return
            await index_target_channel(client)
            if STOP_EVENT.is_set(): return
            await copy_old_posts(client)
            if STOP_EVENT.is_set(): return
            await process_retry_queue(client)
        except Exception as e:
            LOGGER.exception("Copy runner error: %s", e)
        finally:
            RUNNING_TASK = None

# ============================================================
# NEW SOURCE POST
# ============================================================
@Client.on_message(
    filters.channel & (filters.video | filters.document | filters.audio | filters.photo | filters.animation | filters.voice)
)
async def new_source_post(client, message):
    try:
        settings = await get_copy_settings()
        if not settings.get("enabled", False): return
        source_chat = settings.get("source_chat")
        if not source_chat: return
        
        # চ্যানেল অফ থাকলে ডাটাবেসে কিছু সেভ করবে না
        if not settings.get("source_enabled", True) or not settings.get("target_enabled", True):
            return
            
        if int(message.chat.id) != int(source_chat): return
        await create_job(message)
        try:
            await copy_one_message(client, message)
        except FloodWait as e:
            LOGGER.warning("New post FloodWait: %s", e.value)
            await asyncio.sleep(e.value)
            try: await copy_one_message(client, message)
            except Exception as retry_error: LOGGER.error("New post retry failed: %s", retry_error)
        except Exception as e:
            LOGGER.error("New post kept in retry queue: %s", e)
    except Exception as e:
        LOGGER.exception("new_source_post error: %s", e)

# ============================================================
# MAIN MENU
# ============================================================
async def main_menu():
    settings = await get_copy_settings()
    enabled = settings.get("enabled", False)
    source = settings.get("source_chat")
    target = settings.get("target_chat")
    source_on = settings.get("source_enabled", True)
    target_on = settings.get("target_enabled", True)
    language = settings.get("language", "both")
    
    status = "🟢 ON" if enabled else "🔴 OFF"
    source_status = "🟢 ON" if source_on else "🔴 OFF"
    target_status = "🟢 ON" if target_on else "🔴 OFF"
    language_name = {"hindi": "🇮🇳 Hindi", "bangla": "🇧🇩 Bangla", "both": "🌐 Both"}.get(language, "🌐 Both")
    
    return (
        "📋 <b>CHANNEL COPY SYSTEM</b>\n\n"
        f"Status: <b>{status}</b>\n\n"
        f"📥 Source: <b>{source_status}</b>\n<code>{source or 'Not Set'}</code>\n\n"
        f"📤 Target: <b>{target_status}</b>\n<code>{target or 'Not Set'}</code>\n\n"
        f"🌐 Language: <b>{language_name}</b>\n\n"
        "🛡 Duplicate Protection: <b>ON</b>\n"
        "🔄 Retry Queue: <b>ON</b>\n"
        "💾 MongoDB Queue: <b>ON</b>"
    )

# ============================================================
# MAIN KEYBOARD
# ============================================================
async def main_keyboard():
    settings = await get_copy_settings()
    enabled = settings.get("enabled", False)
    language = settings.get("language", "both")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Start Copy", callback_data="cc_start"), InlineKeyboardButton("⛔ Stop", callback_data="cc_stop")],
        [
            InlineKeyboardButton("🇮🇳 Hindi" + (" ✓" if language == "hindi" else ""), callback_data="cc_lang_hindi"),
            InlineKeyboardButton("🇧🇩 Bangla" + (" ✓" if language == "bangla" else ""), callback_data="cc_lang_bangla"),
            InlineKeyboardButton("🌐 Both" + (" ✓" if language == "both" else ""), callback_data="cc_lang_both"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="cc_settings")],
        [InlineKeyboardButton("🗂 Index Target", callback_data="cc_index"), InlineKeyboardButton("🔄 Retry Failed", callback_data="cc_retry")],
        [InlineKeyboardButton("📊 Status", callback_data="cc_status"), InlineKeyboardButton("🔄 Refresh", callback_data="cc_refresh")],
        [InlineKeyboardButton("❌ Close", callback_data="cc_close")]
    ])

# ============================================================
# SETTINGS KEYBOARD
# ============================================================
async def settings_keyboard():
    settings = await get_copy_settings()
    source = settings.get("source_chat")
    target = settings.get("target_chat")
    source_on = settings.get("source_enabled", True)
    target_on = settings.get("target_enabled", True)
    
    buttons = []
    
    # --- সোর্স চ্যানেল অন/অফ এবং ডিলিট ---
    if source:
        source_btn_text = "🔴 Source OFF" if source_on else "🟢 Source ON"
        buttons.append([InlineKeyboardButton(source_btn_text, callback_data="cc_toggle_source")])
        buttons.append([InlineKeyboardButton("🗑 Delete Source", callback_data="cc_del_source")])
    else:
        buttons.append([InlineKeyboardButton("📥 Set Source Channel", callback_data="cc_set_source")])
        
    # --- টার্গেট চ্যানেল অন/অফ এবং ডিলিট ---
    if target:
        target_btn_text = "🔴 Target OFF" if target_on else "🟢 Target ON"
        buttons.append([InlineKeyboardButton(target_btn_text, callback_data="cc_toggle_target")])
        buttons.append([InlineKeyboardButton("🗑 Delete Target", callback_data="cc_del_target")])
    else:
        buttons.append([InlineKeyboardButton("📤 Set Target Channel", callback_data="cc_set_target")])

    # --- ভাষা নির্বাচন ---
    buttons.append([
        InlineKeyboardButton("🇮🇳 Hindi", callback_data="cc_lang_hindi"),
        InlineKeyboardButton("🇧🇩 Bangla", callback_data="cc_lang_bangla"),
        InlineKeyboardButton("🌐 Both", callback_data="cc_lang_both"),
    ])
    
    # --- অল ডিলিট (সব হিস্ট্রি মুছে ফেলার বাটন) ---
    buttons.append([InlineKeyboardButton("🧹 Delete All History", callback_data="cc_delete_data")])
    
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="cc_back"), InlineKeyboardButton("❌ Close", callback_data="cc_close")])
    
    return InlineKeyboardMarkup(buttons)

# ============================================================
# /copy COMMAND
# ============================================================
@Client.on_message(filters.private & filters.command("copy"))
async def copy_command(client, message):
    if message.from_user.id not in ADMINS: return
    await message.reply_text(await main_menu(), reply_markup=await main_keyboard(), parse_mode=enums.ParseMode.HTML)

# ============================================================
# CALLBACK HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^cc_"))
async def copy_callback(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return
    data = query.data

    if data == "cc_start":
        settings = await get_copy_settings()
        if not settings.get("source_chat"):
            await query.answer("❌ Source channel set করুন।", show_alert=True)
            return
        if not settings.get("target_chat"):
            await query.answer("❌ Target channel set করুন।", show_alert=True)
            return
        await update_copy_settings({"enabled": True})
        STOP_EVENT.clear()
        global RUNNING_TASK
        if RUNNING_TASK is None or RUNNING_TASK.done():
            RUNNING_TASK = asyncio.create_task(run_copy_system(client))
        await query.answer("▶️ Copy Started")

    elif data == "cc_stop":
        STOP_EVENT.set()
        await update_copy_settings({"enabled": False})
        await query.answer("⛔ Copy Stopped")

    elif data == "cc_lang_hindi":
        await update_copy_settings({"language": "hindi"})
        await query.answer("🇮🇳 Hindi selected")
    elif data == "cc_lang_bangla":
        await update_copy_settings({"language": "bangla"})
        await query.answer("🇧🇩 Bangla selected")
    elif data == "cc_lang_both":
        await update_copy_settings({"language": "both"})
        await query.answer("🌐 Both selected")

    elif data == "cc_settings":
        await query.message.edit_text("⚙️ <b>COPY SETTINGS</b>\n\nনিচের Button থেকে Source ও Target Channel সেট করুন।", reply_markup=await settings_keyboard(), parse_mode=enums.ParseMode.HTML)
        await query.answer()
        return

    elif data == "cc_set_source":
        ADMIN_STATE[query.from_user.id] = "source"
        await query.message.edit_text("📥 <b>Set Source Channel</b>\n\nএখন Source Channel-এর <b>@username</b> অথবা <b>Chat ID</b> পাঠান।\n\nউদাহরণ:\n<code>@mychannel</code>", parse_mode=enums.ParseMode.HTML)
        await query.answer()
        return

    elif data == "cc_set_target":
        ADMIN_STATE[query.from_user.id] = "target"
        await query.message.edit_text("📤 <b>Set Target Channel</b>\n\nএখন Target Channel-এর <b>@username</b> অথবা <b>Chat ID</b> পাঠান।\n\nউদাহরণ:\n<code>@targetchannel</code>", parse_mode=enums.ParseMode.HTML)
        await query.answer()
        return

    # ----- চ্যানেল অন/অফ এবং ডিলিট করার কোড -----
    elif data == "cc_toggle_source":
        settings = await get_copy_settings()
        await update_copy_settings({"source_enabled": not settings.get("source_enabled", True)})
        await query.answer("Source Toggled!")

    elif data == "cc_toggle_target":
        settings = await get_copy_settings()
        await update_copy_settings({"target_enabled": not settings.get("target_enabled", True)})
        await query.answer("Target Toggled!")

    elif data == "cc_del_source":
        await update_copy_settings({"source_chat": None, "source_enabled": True})
        await query.answer("Source channel deleted!")

    elif data == "cc_del_target":
        await update_copy_settings({"target_chat": None, "target_enabled": True})
        await query.answer("Target channel deleted!")

    elif data == "cc_delete_data":
        await clear_copy_database() # ডাটাবেস মুছে ফেলার ফাংশন
        await query.answer("All copy history deleted!", show_alert=True)
    # ------------------------------------------------

    elif data == "cc_index":
        settings = await get_copy_settings()
        if not settings.get("target_chat"):
            await query.answer("❌ Target channel set করুন।", show_alert=True)
            return
        await query.answer("🗂 Target indexing started.")
        async def do_index():
            try: await index_target_channel(client)
            except Exception as e: LOGGER.exception("Target index error: %s", e)
        asyncio.create_task(do_index())

    elif data == "cc_retry":
        await query.answer("🔄 Retry started.")
        asyncio.create_task(process_retry_queue(client))

    elif data == "cc_status":
        try:
            pending = await copy_col.count_documents({"type": "copy_job", "status": "pending"})
            processing = await copy_col.count_documents({"type": "copy_job", "status": "processing"})
            copied = await copy_col.count_documents({"type": "copy_job", "status": "copied"})
            retry = await copy_col.count_documents({"type": "copy_job", "status": "retry"})
            duplicate = await copy_col.count_documents({"type": "copy_job", "status": "skipped_target_duplicate"})
            language_skip = await copy_col.count_documents({"type": "copy_job", "status": "skipped_language"})
            target_count = await copy_col.count_documents({"type": "target_file"})
            await query.answer(f"📊 STATUS\n\n✅ Copied: {copied}\n⏳ Pending: {pending}\n⚙️ Processing: {processing}\n🔄 Retry: {retry}\n⛔ Duplicate: {duplicate}\n🌐 Language Skip: {language_skip}\n🗂 Target Indexed: {target_count}", show_alert=True)
        except Exception as e:
            LOGGER.exception("Status error: %s", e)
            await query.answer("❌ Status unavailable.", show_alert=True)

    elif data == "cc_back":
        await query.message.edit_text(await main_menu(), reply_markup=await main_keyboard(), parse_mode=enums.ParseMode.HTML)
        await query.answer()
        return

    elif data == "cc_refresh":
        await query.answer("🔄 Refreshed")

    elif data == "cc_close":
        await query.answer("Menu Closed")
        await query.message.delete()
        return

    # সেটিংস মেনুর ভেতরে থাকলে সেটিংস মেনু আপডেট হবে, নাহলে মেইন মেনু
    try:
        if data in ["cc_settings", "cc_toggle_source", "cc_toggle_target", "cc_del_source", "cc_del_target", "cc_delete_data"]:
            await query.message.edit_text("⚙️ <b>COPY SETTINGS</b>\n\nনিচের Button থেকে Source ও Target Channel সেট করুন।", reply_markup=await settings_keyboard(), parse_mode=enums.ParseMode.HTML)
        else:
            await query.message.edit_text(await main_menu(), reply_markup=await main_keyboard(), parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass

# ============================================================
# ADMIN TEXT INPUT (কনফ্লিক্ট ফিক্স করা হয়েছে)
# ============================================================
@Client.on_message(
    filters.private
    & filters.text
    & ~filters.command(["cancel", "start", "cleaner", "id", "stats", "copy"])
)
async def copy_admin_text_input(client, message):
    user_id = message.from_user.id
    if user_id not in ADMINS: return
    
    # ক্লিনারের স্টেট চেক করা হচ্ছে
    if CLEANER_STATE.get(user_id) == "add":
        return
        
    state = ADMIN_STATE.get(user_id)
    if state not in ("source", "target"): return

    value = message.text.strip()
    if not value:
        await message.reply_text("❌ Empty value.")
        return

    try:
        chat = await client.get_chat(value)
        if chat.type != enums.ChatType.CHANNEL:
            await message.reply_text("❌ এটি Telegram Channel নয়।")
            return

        if state == "source":
            await update_copy_settings({"source_chat": int(chat.id)})
            text = f"✅ <b>Source Channel Set</b>\n\n📥 {chat.title}\n<code>{chat.id}</code>"
        else:
            await update_copy_settings({"target_chat": int(chat.id)})
            text = f"✅ <b>Target Channel Set</b>\n\n📤 {chat.title}\n<code>{chat.id}</code>"

        ADMIN_STATE.pop(user_id, None)
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
        await message.reply_text(await main_menu(), reply_markup=await main_keyboard(), parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        LOGGER.exception("Channel setup error: %s", e)
        await message.reply_text("❌ Channel set করা যায়নি।\n\nসঠিক @username অথবা Chat ID দিন।\n\n<code>" + str(e)[:500] + "</code>", parse_mode=enums.ParseMode.HTML)

# ============================================================
# MONGODB INDEXES & INITIALIZATION
# ============================================================
async def create_indexes():
    try: await copy_col.create_index([("type", 1), ("job_key", 1)], unique=True, name="copy_job_unique")
    except Exception as e: LOGGER.debug("copy_job_unique: %s", e)
    try: await copy_col.create_index([("type", 1), ("file_unique_id", 1)], name="file_unique_id_index")
    except Exception as e: LOGGER.debug("file_unique_id_index: %s", e)
    try: await copy_col.create_index([("type", 1), ("status", 1)], name="status_index")
    except Exception as e: LOGGER.debug("status_index: %s", e)

async def initialize_copy_system():
    try:
        await create_indexes()
        await get_copy_settings()
        LOGGER.info("Channel Copy System initialized.")
    except Exception as e:
        LOGGER.exception("Copy system initialization error: %s", e)
