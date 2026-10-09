# ©️ DramaZ.botz | @ 👨‍💻 Developer: DramaZ.botz | NT_BOT_CHANNEL
#
# Advanced Telegram Channel Copy System
# Source Channel -> Target Channel
# COPY, NOT FORWARD
#
# Features:
# - Old source posts
# - New source posts
# - Target duplicate protection
# - Source duplicate protection
# - Hindi / Bangla / Both
# - Mixed language safe
# - MongoDB queue
# - Retry queue
# - Resume after restart
# - Video / Document / Photo / Audio / Animation / Voice
# - Caption preserved
# - Admin button control
# - No command required after opening /copy
# - Close button added
#
# Existing project imports:
#   from info import ADMINS
#   from plugins.database.database import db


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


# ============================================================
# LOGGER
# ============================================================

LOGGER = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

COLLECTION_NAME = "channel_copy"

copy_col = db.db[COLLECTION_NAME]

SETTINGS_ID = "settings"


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_SETTINGS = {
    "_id": SETTINGS_ID,

    "enabled": False,

    "source_chat": None,
    "target_chat": None,

    "language": "both",

    "retry_delay": 30,

    "created_at": None,
    "updated_at": None,
}


# ============================================================
# RUNTIME
# ============================================================

COPY_LOCK = asyncio.Lock()

STOP_EVENT = asyncio.Event()

RUNNING_TASK = None

# Admin setup states
ADMIN_STATE = {}


# ============================================================
# DATABASE SETTINGS
# ============================================================

async def get_settings():
    try:
        data = await copy_col.find_one(
            {"_id": SETTINGS_ID}
        )

        if not data:
            data = DEFAULT_SETTINGS.copy()

            now = datetime.now(timezone.utc)

            data["created_at"] = now
            data["updated_at"] = now

            await copy_col.insert_one(
                data.copy()
            )

        return data

    except Exception as e:
        LOGGER.exception(
            "get_settings error: %s",
            e,
        )

        return DEFAULT_SETTINGS.copy()


async def update_settings(data):
    try:
        data = dict(data)

        data["updated_at"] = (
            datetime.now(timezone.utc)
        )

        await copy_col.update_one(
            {"_id": SETTINGS_ID},
            {"$set": data},
            upsert=True,
        )

        return True

    except Exception as e:
        LOGGER.exception(
            "update_settings error: %s",
            e,
        )

        return False


# ============================================================
# MEDIA HELPERS
# ============================================================

def get_media(message):

    if message.photo:
        return "photo", message.photo

    if message.video:
        return "video", message.video

    if message.document:
        return "document", message.document

    if message.audio:
        return "audio", message.audio

    if message.animation:
        return "animation", message.animation

    if message.voice:
        return "voice", message.voice

    return None, None


def get_file_unique_id(message):

    _, media = get_media(message)

    if not media:
        return None

    return getattr(
        media,
        "file_unique_id",
        None,
    )


def get_file_name(message):

    if message.document:
        return (
            message.document.file_name
            or ""
        )

    if message.video:
        return (
            message.video.file_name
            or ""
        )

    if message.audio:
        return (
            message.audio.file_name
            or ""
        )

    if message.animation:
        return (
            message.animation.file_name
            or ""
        )

    if message.photo:
        return "photo"

    return ""


def get_file_size(message):

    _, media = get_media(message)

    if not media:
        return 0

    return int(
        getattr(
            media,
            "file_size",
            0,
        )
        or 0
    )


# ============================================================
# LANGUAGE DETECTION
# ============================================================

BANGLA_RE = re.compile(
    r"[\u0980-\u09FF]"
)

DEVANAGARI_RE = re.compile(
    r"[\u0900-\u097F]"
)


def detect_language(message):

    try:

        filename = get_file_name(
            message
        )

        caption = (
            message.caption
            or ""
        )

        text = (
            f"{filename}\n"
            f"{caption}"
        )

        if not text.strip():
            return "unknown"

        has_bangla = bool(
            BANGLA_RE.search(text)
        )

        has_hindi = bool(
            DEVANAGARI_RE.search(text)
        )

        if has_bangla and has_hindi:
            return "mixed"

        if has_bangla:
            return "bangla"

        if has_hindi:
            return "hindi"

        return "unknown"

    except Exception as e:

        LOGGER.warning(
            "Language detection failed: %s",
            e,
        )

        return "unknown"


def language_allowed(message, mode):

    try:

        mode = (
            str(mode or "both")
            .lower()
        )

        detected = detect_language(
            message
        )

        if mode == "both":
            return True

        if mode == "hindi":

            return detected in (
                "hindi",
                "mixed",
            )

        if mode == "bangla":

            return detected in (
                "bangla",
                "mixed",
            )

        return True

    except Exception as e:

        # Never crash because of
        # language detection.

        LOGGER.warning(
            "language_allowed error: %s",
            e,
        )

        return True


# ============================================================
# FILENAME NORMALIZATION
# ============================================================

def normalize_filename(name):

    if not name:
        return ""

    try:

        name = name.lower()

        name = re.sub(
            r"\.(mkv|mp4|avi|mov|wmv|flv|webm|"
            r"mp3|m4a|aac|flac|zip|rar|7z)$",
            "",
            name,
            flags=re.IGNORECASE,
        )

        name = re.sub(
            r"[\W_]+",
            "",
            name,
            flags=re.UNICODE,
        )

        return name.strip()

    except Exception:

        return str(name).lower().strip()


# ============================================================
# JOB KEY
# ============================================================

def make_job_key(message):

    unique_id = get_file_unique_id(
        message
    )

    if unique_id:
        return f"file:{unique_id}"

    return (
        f"message:"
        f"{message.chat.id}:"
        f"{message.id}"
    )


# ============================================================
# TARGET DUPLICATE CHECK
# ============================================================

async def target_file_exists(message):

    unique_id = get_file_unique_id(
        message
    )

    if unique_id:

        found = await copy_col.find_one(
            {
                "type": "target_file",
                "file_unique_id":
                    unique_id,
            }
        )

        if found:
            return True

    filename = normalize_filename(
        get_file_name(message)
    )

    size = get_file_size(message)

    if filename and size:

        found = await copy_col.find_one(
            {
                "type": "target_file",
                "normalized_filename":
                    filename,
                "file_size":
                    size,
            }
        )

        if found:
            return True

    return False


# ============================================================
# MARK TARGET FILE
# ============================================================

async def mark_target_file(
    message,
    target_message_id,
):

    try:

        unique_id = (
            get_file_unique_id(message)
        )

        filename = get_file_name(
            message
        )

        await copy_col.update_one(
            {
                "type": "target_file",

                "target_message_id":
                    int(target_message_id),
            },

            {
                "$set": {
                    "type":
                        "target_file",

                    "file_unique_id":
                        unique_id,

                    "normalized_filename":
                        normalize_filename(
                            filename
                        ),

                    "filename":
                        filename,

                    "file_size":
                        get_file_size(
                            message
                        ),

                    "target_message_id":
                        int(
                            target_message_id
                        ),

                    "indexed_at":
                        datetime.now(
                            timezone.utc
                        ),
                }
            },

            upsert=True,
        )

    except Exception as e:

        LOGGER.exception(
            "mark_target_file error: %s",
            e,
        )


# ============================================================
# JOB FUNCTIONS
# ============================================================

async def get_job(message):

    return await copy_col.find_one(
        {
            "type": "copy_job",
            "job_key":
                make_job_key(message),
        }
    )


async def create_job(message):

    key = make_job_key(message)

    existing = await copy_col.find_one(
        {
            "type": "copy_job",
            "job_key": key,
        }
    )

    if existing:
        return existing

    job = {
        "type": "copy_job",

        "job_key": key,

        "source_chat":
            int(message.chat.id),

        "source_message_id":
            int(message.id),

        "file_unique_id":
            get_file_unique_id(message),

        "filename":
            get_file_name(message),

        "normalized_filename":
            normalize_filename(
                get_file_name(message)
            ),

        "file_size":
            get_file_size(message),

        "language":
            detect_language(message),

        "status":
            "pending",

        "retry_count":
            0,

        "last_error":
            None,

        "target_message_id":
            None,

        "created_at":
            datetime.now(
                timezone.utc
            ),

        "updated_at":
            datetime.now(
                timezone.utc
            ),
    }

    try:

        await copy_col.insert_one(
            job
        )

        return job

    except Exception:

        return await get_job(
            message
        )


async def update_job(
    message,
    data,
):

    data = dict(data)

    data["updated_at"] = (
        datetime.now(
            timezone.utc
        )
    )

    await copy_col.update_one(
        {
            "type": "copy_job",

            "job_key":
                make_job_key(message),
        },

        {
            "$set": data
        },

        upsert=True,
    )


# ============================================================
# COPY ONE MESSAGE
# ============================================================

async def copy_one_message(
    client,
    message,
):

    settings = await get_settings()

    target_chat = settings.get(
        "target_chat"
    )

    if not target_chat:

        raise RuntimeError(
            "Target channel is not configured."
        )

    # --------------------------------------------------------
    # Language
    # --------------------------------------------------------

    if not language_allowed(
        message,
        settings.get(
            "language",
            "both",
        ),
    ):

        await create_job(
            message
        )

        await update_job(
            message,
            {
                "status":
                    "skipped_language",
            },
        )

        return "skipped_language"

    # --------------------------------------------------------
    # Target duplicate
    # --------------------------------------------------------

    if await target_file_exists(
        message
    ):

        await create_job(
            message
        )

        await update_job(
            message,
            {
                "status":
                    "skipped_target_duplicate",
            },
        )

        return "skipped_target_duplicate"

    # --------------------------------------------------------
    # Create job
    # --------------------------------------------------------

    await create_job(
        message
    )

    await update_job(
        message,
        {
            "status":
                "processing",

            "last_error":
                None,
        }
    )

    # --------------------------------------------------------
    # COPY
    # --------------------------------------------------------

    try:

        copied = await client.copy_message(
            chat_id=target_chat,

            from_chat_id=
                message.chat.id,

            message_id=
                message.id,
        )

        target_message_id = (
            copied.id
            if copied
            else None
        )

        await update_job(
            message,
            {
                "status":
                    "copied",

                "target_message_id":
                    target_message_id,

                "last_error":
                    None,

                "copied_at":
                    datetime.now(
                        timezone.utc
                    ),
            },
        )

        if target_message_id:

            await mark_target_file(
                message,
                target_message_id,
            )

        LOGGER.info(
            "Copied: %s/%s -> %s/%s",
            message.chat.id,
            message.id,
            target_chat,
            target_message_id,
        )

        return "copied"

    except FloodWait as e:

        job = await get_job(
            message
        )

        retry_count = int(
            job.get(
                "retry_count",
                0,
            )
            if job
            else 0
        )

        await update_job(
            message,
            {
                "status":
                    "retry",

                "retry_count":
                    retry_count + 1,

                "last_error":
                    f"FloodWait: {e.value}",
            },
        )

        raise

    except Exception as e:

        job = await get_job(
            message
        )

        retry_count = int(
            job.get(
                "retry_count",
                0,
            )
            if job
            else 0
        )

        await update_job(
            message,
            {
                "status":
                    "retry",

                "retry_count":
                    retry_count + 1,

                "last_error":
                    str(e)[:2000],
            },
        )

        raise


# ============================================================
# INDEX TARGET CHANNEL
# ============================================================

async def index_target_channel(
    client
):

    settings = await get_settings()

    target_chat = settings.get(
        "target_chat"
    )

    if not target_chat:

        raise RuntimeError(
            "Target channel is not configured."
        )

    count = 0

    async for message in client.get_chat_history(
        target_chat
    ):

        if STOP_EVENT.is_set():
            break

        if not get_media(message)[0]:
            continue

        await mark_target_file(
            message,
            message.id,
        )

        count += 1

    LOGGER.info(
        "Target indexed: %s",
        count,
    )

    return count


# ============================================================
# OLD SOURCE COPY
# ============================================================

async def copy_old_posts(
    client
):

    settings = await get_settings()

    source_chat = settings.get(
        "source_chat"
    )

    if not source_chat:

        raise RuntimeError(
            "Source channel is not configured."
        )

    total = 0
    copied = 0
    skipped = 0
    errors = 0

    async for message in client.get_chat_history(
        source_chat
    ):

        if STOP_EVENT.is_set():
            break

        if not get_media(message)[0]:
            continue

        total += 1

        try:

            result = await copy_one_message(
                client,
                message,
            )

            if result == "copied":
                copied += 1
            else:
                skipped += 1

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

        except Exception as e:

            errors += 1

            LOGGER.error(
                "Copy failed; kept in retry queue | "
                "message=%s | %s",
                message.id,
                e,
            )

        await asyncio.sleep(
            0.5
        )

    LOGGER.info(
        "Old copy finished | "
        "total=%s copied=%s skipped=%s errors=%s",
        total,
        copied,
        skipped,
        errors,
    )


# ============================================================
# RETRY QUEUE
# ============================================================

async def process_retry_queue(
    client
):

    settings = await get_settings()

    source_chat = settings.get(
        "source_chat"
    )

    if not source_chat:
        return

    cursor = copy_col.find(
        {
            "type":
                "copy_job",

            "status":
                "retry",
        }
    ).sort(
        "updated_at",
        1,
    ).limit(50)

    async for job in cursor:

        if STOP_EVENT.is_set():
            return

        message_id = job.get(
            "source_message_id"
        )

        try:

            message = await client.get_messages(
                source_chat,
                message_id,
            )

            if not message:
                continue

            try:

                await copy_one_message(
                    client,
                    message,
                )

            except FloodWait as e:

                await asyncio.sleep(
                    e.value
                )

            except Exception as e:

                LOGGER.warning(
                    "Retry failed: %s | %s",
                    message_id,
                    e,
                )

            await asyncio.sleep(
                int(
                    settings.get(
                        "retry_delay",
                        30,
                    )
                )
            )

        except Exception as e:

            LOGGER.warning(
                "Retry get message failed: %s",
                e,
            )


# ============================================================
# FULL OLD COPY RUNNER
# ============================================================

async def run_copy_system(
    client
):

    global RUNNING_TASK

    if COPY_LOCK.locked():
        return

    async with COPY_LOCK:

        try:

            settings = await get_settings()

            if not settings.get(
                "enabled",
                False,
            ):
                return

            # First make Target index
            await index_target_channel(
                client
            )

            if STOP_EVENT.is_set():
                return

            # Then old Source
            await copy_old_posts(
                client
            )

            if STOP_EVENT.is_set():
                return

            # Retry failed
            await process_retry_queue(
                client
            )

        except Exception as e:

            LOGGER.exception(
                "Copy runner error: %s",
                e,
            )

        finally:

            RUNNING_TASK = None


# ============================================================
# NEW SOURCE POST
# ============================================================

@Client.on_message(
    filters.channel
    & (
        filters.video
        | filters.document
        | filters.audio
        | filters.photo
        | filters.animation
        | filters.voice
    )
)
async def new_source_post(
    client,
    message,
):

    try:

        settings = await get_settings()

        if not settings.get(
            "enabled",
            False,
        ):
            return

        source_chat = settings.get(
            "source_chat"
        )

        if not source_chat:
            return

        if int(message.chat.id) != int(
            source_chat
        ):
            return

        await create_job(
            message
        )

        try:

            await copy_one_message(
                client,
                message,
            )

        except FloodWait as e:

            LOGGER.warning(
                "New post FloodWait: %s",
                e.value,
            )

            await asyncio.sleep(
                e.value
            )

            try:

                await copy_one_message(
                    client,
                    message,
                )

            except Exception as retry_error:

                LOGGER.error(
                    "New post retry failed: %s",
                    retry_error,
                )

        except Exception as e:

            LOGGER.error(
                "New post kept in retry queue: %s",
                e,
            )

    except Exception as e:

        LOGGER.exception(
            "new_source_post error: %s",
            e,
        )


# ============================================================
# MAIN MENU
# ============================================================

async def main_menu():

    settings = await get_settings()

    enabled = settings.get(
        "enabled",
        False,
    )

    source = settings.get(
        "source_chat"
    )

    target = settings.get(
        "target_chat"
    )

    language = settings.get(
        "language",
        "both",
    )

    status = (
        "🟢 ON"
        if enabled
        else
        "🔴 OFF"
    )

    language_name = {
        "hindi":
            "🇮🇳 Hindi",

        "bangla":
            "🇧🇩 Bangla",

        "both":
            "🌐 Both",
    }.get(
        language,
        "🌐 Both",
    )

    return (
        "📋 <b>CHANNEL COPY SYSTEM</b>\n\n"

        f"Status: <b>{status}</b>\n\n"

        "📥 Source:\n"
        f"<code>{source or 'Not Set'}</code>\n\n"

        "📤 Target:\n"
        f"<code>{target or 'Not Set'}</code>\n\n"

        f"🌐 Language: "
        f"<b>{language_name}</b>\n\n"

        "🛡 Duplicate Protection: "
        "<b>ON</b>\n"

        "🔄 Retry Queue: "
        "<b>ON</b>\n"

        "💾 MongoDB Queue: "
        "<b>ON</b>"
    )


# ============================================================
# MAIN KEYBOARD
# ============================================================

async def main_keyboard():

    settings = await get_settings()

    enabled = settings.get(
        "enabled",
        False,
    )

    language = settings.get(
        "language",
        "both",
    )

    return InlineKeyboardMarkup([

        # Start / Stop
        [
            InlineKeyboardButton(
                "▶️ Start Copy",
                callback_data=
                    "cc_start",
            ),

            InlineKeyboardButton(
                "⛔ Stop",
                callback_data=
                    "cc_stop",
            ),
        ],

        # Language
        [
            InlineKeyboardButton(
                "🇮🇳 Hindi"
                + (
                    " ✓"
                    if language ==
                    "hindi"
                    else ""
                ),
                callback_data=
                    "cc_lang_hindi",
            ),

            InlineKeyboardButton(
                "🇧🇩 Bangla"
                + (
                    " ✓"
                    if language ==
                    "bangla"
                    else ""
                ),
                callback_data=
                    "cc_lang_bangla",
            ),

            InlineKeyboardButton(
                "🌐 Both"
                + (
                    " ✓"
                    if language ==
                    "both"
                    else ""
                ),
                callback_data=
                    "cc_lang_both",
            ),
        ],

        # Settings
        [
            InlineKeyboardButton(
                "⚙️ Settings",
                callback_data=
                    "cc_settings",
            ),
        ],

        # Tools
        [
            InlineKeyboardButton(
                "🗂 Index Target",
                callback_data=
                    "cc_index",
            ),

            InlineKeyboardButton(
                "🔄 Retry Failed",
                callback_data=
                    "cc_retry",
            ),
        ],

        # Status
        [
            InlineKeyboardButton(
                "📊 Status",
                callback_data=
                    "cc_status",
            ),

            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data=
                    "cc_refresh",
            ),
        ],
        
        # Close Button
        [
            InlineKeyboardButton(
                "❌ Close",
                callback_data=
                    "cc_close",
            )
        ],
    ])


# ============================================================
# SETTINGS MENU
# ============================================================

async def settings_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📥 Set Source Channel",
                callback_data=
                    "cc_set_source",
            )
        ],

        [
            InlineKeyboardButton(
                "📤 Set Target Channel",
                callback_data=
                    "cc_set_target",
            )
        ],

        [
            InlineKeyboardButton(
                "🇮🇳 Hindi",
                callback_data=
                    "cc_lang_hindi",
            ),

            InlineKeyboardButton(
                "🇧🇩 Bangla",
                callback_data=
                    "cc_lang_bangla",
            ),

            InlineKeyboardButton(
                "🌐 Both",
                callback_data=
                    "cc_lang_both",
            ),
        ],

        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data=
                    "cc_back",
            ),
            
            InlineKeyboardButton(
                "❌ Close",
                callback_data=
                    "cc_close",
            )
        ],
    ])


# ============================================================
# /copy ONLY TO OPEN MENU
# ============================================================

@Client.on_message(
    filters.private
    & filters.command("copy")
)
async def copy_command(
    client,
    message,
):

    if message.from_user.id not in ADMINS:
        return

    await message.reply_text(
        await main_menu(),
        reply_markup=
            await main_keyboard(),
        parse_mode=
            enums.ParseMode.HTML,
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^cc_")
)
async def copy_callback(
    client,
    query,
):

    if query.from_user.id not in ADMINS:

        await query.answer(
            "Admins only!",
            show_alert=True,
        )

        return

    data = query.data

    # ========================================================
    # START
    # ========================================================

    if data == "cc_start":

        settings = await get_settings()

        if not settings.get(
            "source_chat"
        ):

            await query.answer(
                "❌ Source channel set করুন।",
                show_alert=True,
            )

            return

        if not settings.get(
            "target_chat"
        ):

            await query.answer(
                "❌ Target channel set করুন।",
                show_alert=True,
            )

            return

        await update_settings({
            "enabled":
                True,
        })

        STOP_EVENT.clear()

        global RUNNING_TASK

        if (
            RUNNING_TASK is None
            or RUNNING_TASK.done()
        ):

            RUNNING_TASK = (
                asyncio.create_task(
                    run_copy_system(
                        client
                    )
                )
            )

        await query.answer(
            "▶️ Copy Started"
        )

    # ========================================================
    # STOP
    # ========================================================

    elif data == "cc_stop":

        STOP_EVENT.set()

        await update_settings({
            "enabled":
                False,
        })

        await query.answer(
            "⛔ Copy Stopped"
        )

    # ========================================================
    # LANGUAGE
    # ========================================================

    elif data == "cc_lang_hindi":

        await update_settings({
            "language":
                "hindi"
        })

        await query.answer(
            "🇮🇳 Hindi selected"
        )

    elif data == "cc_lang_bangla":

        await update_settings({
            "language":
                "bangla"
        })

        await query.answer(
            "🇧🇩 Bangla selected"
        )

    elif data == "cc_lang_both":

        await update_settings({
            "language":
                "both"
        })

        await query.answer(
            "🌐 Both selected"
        )

    # ========================================================
    # SETTINGS
    # ========================================================

    elif data == "cc_settings":

        await query.message.edit_text(
            "⚙️ <b>COPY SETTINGS</b>\n\n"
            "নিচের Button থেকে Source ও "
            "Target Channel সেট করুন।",
            reply_markup=
                await settings_keyboard(),
            parse_mode=
                enums.ParseMode.HTML,
        )

        await query.answer()

        return

    # ========================================================
    # SET SOURCE
    # ========================================================

    elif data == "cc_set_source":

        ADMIN_STATE[
            query.from_user.id
        ] = "source"

        await query.message.edit_text(
            "📥 <b>Set Source Channel</b>\n\n"
            "এখন Source Channel-এর "
            "<b>@username</b> অথবা "
            "<b>Chat ID</b> পাঠান।\n\n"
            "উদাহরণ:\n"
            "<code>@mychannel</code>",
            parse_mode=
                enums.ParseMode.HTML,
        )

        await query.answer()

        return

    # ========================================================
    # SET TARGET
    # ========================================================

    elif data == "cc_set_target":

        ADMIN_STATE[
            query.from_user.id
        ] = "target"

        await query.message.edit_text(
            "📤 <b>Set Target Channel</b>\n\n"
            "এখন Target Channel-এর "
            "<b>@username</b> অথবা "
            "<b>Chat ID</b> পাঠান।\n\n"
            "উদাহরণ:\n"
            "<code>@targetchannel</code>",
            parse_mode=
                enums.ParseMode.HTML,
        )

        await query.answer()

        return

    # ========================================================
    # INDEX
    # ========================================================

    elif data == "cc_index":

        settings = await get_settings()

        if not settings.get(
            "target_chat"
        ):

            await query.answer(
                "❌ Target channel set করুন।",
                show_alert=True,
            )

            return

        await query.answer(
            "🗂 Target indexing started."
        )

        async def do_index():

            try:

                count = (
                    await index_target_channel(
                        client
                    )
                )

                LOGGER.info(
                    "Target index complete: %s",
                    count,
                )

            except Exception as e:

                LOGGER.exception(
                    "Target index error: %s",
                    e,
                )

        asyncio.create_task(
            do_index()
        )

    # ========================================================
    # RETRY
    # ========================================================

    elif data == "cc_retry":

        await query.answer(
            "🔄 Retry started."
        )

        asyncio.create_task(
            process_retry_queue(
                client
            )
        )

    # ========================================================
    # STATUS
    # ========================================================

    elif data == "cc_status":

        try:

            pending = (
                await copy_col.count_documents(
                    {
                        "type":
                            "copy_job",

                        "status":
                            "pending",
                    }
                )
            )

            processing = (
                await copy_col.count_documents(
                    {
                        "type":
                            "copy_job",

                        "status":
                            "processing",
                    }
                )
            )

            copied = (
                await copy_col.count_documents(
                    {
                        "type":
                            "copy_job",

                        "status":
                            "copied",
                    }
                )
            )

            retry = (
                await copy_col.count_documents(
                    {
                        "type":
                            "copy_job",

                        "status":
                            "retry",
                    }
                )
            )

            duplicate = (
                await copy_col.count_documents(
                    {
                        "type":
                            "copy_job",

                        "status":
                            "skipped_target_duplicate",
                    }
                )
            )

            language_skip = (
                await copy_col.count_documents(
                    {
                        "type":
                            "copy_job",

                        "status":
                            "skipped_language",
                    }
                )
            )

            target_count = (
                await copy_col.count_documents(
                    {
                        "type":
                            "target_file",
                    }
                )
            )

            await query.answer(
                "📊 STATUS\n\n"
                f"✅ Copied: {copied}\n"
                f"⏳ Pending: {pending}\n"
                f"⚙️ Processing: {processing}\n"
                f"🔄 Retry: {retry}\n"
                f"⛔ Duplicate: {duplicate}\n"
                f"🌐 Language Skip: {language_skip}\n"
                f"🗂 Target Indexed: {target_count}",
                show_alert=True,
            )

        except Exception as e:

            LOGGER.exception(
                "Status error: %s",
                e,
            )

            await query.answer(
                "❌ Status unavailable.",
                show_alert=True,
            )

    # ========================================================
    # BACK
    # ========================================================

    elif data == "cc_back":

        await query.message.edit_text(
            await main_menu(),
            reply_markup=
                await main_keyboard(),
            parse_mode=
                enums.ParseMode.HTML,
        )

        await query.answer()

        return

    # ========================================================
    # REFRESH
    # ========================================================

    elif data == "cc_refresh":

        await query.answer(
            "🔄 Refreshed"
        )

    # ========================================================
    # CLOSE BUTTON (নতুন যোগ করা হয়েছে)
    # ========================================================

    elif data == "cc_close":

        await query.answer(
            "Menu Closed"
        )
        
        await query.message.delete()
        
        return

    # ========================================================
    # UPDATE MAIN MENU
    # ========================================================

    try:

        await query.message.edit_text(
            await main_menu(),
            reply_markup=
                await main_keyboard(),
            parse_mode=
                enums.ParseMode.HTML,
        )

    except Exception:
        pass


# ============================================================
# ADMIN TEXT INPUT
# ============================================================

@Client.on_message(
    filters.private
    & filters.text
)
async def copy_admin_text_input(
    client,
    message,
):

    user_id = message.from_user.id

    if user_id not in ADMINS:
        return

    state = ADMIN_STATE.get(
        user_id
    )

    if state not in (
        "source",
        "target",
    ):
        return

    value = (
        message.text.strip()
    )

    if not value:

        await message.reply_text(
            "❌ Empty value."
        )

        return

    try:

        chat = await client.get_chat(
            value
        )

        if chat.type != enums.ChatType.CHANNEL:

            await message.reply_text(
                "❌ এটি Telegram Channel নয়।"
            )

            return

        if state == "source":

            await update_settings({
                "source_chat":
                    int(chat.id)
            })

            text = (
                "✅ <b>Source Channel Set</b>\n\n"
                f"📥 {chat.title}\n"
                f"<code>{chat.id}</code>"
            )

        else:

            await update_settings({
                "target_chat":
                    int(chat.id)
            })

            text = (
                "✅ <b>Target Channel Set</b>\n\n"
                f"📤 {chat.title}\n"
                f"<code>{chat.id}</code>"
            )

        ADMIN_STATE.pop(
            user_id,
            None,
        )

        await message.reply_text(
            text,
            parse_mode=
                enums.ParseMode.HTML,
        )

        await message.reply_text(
            await main_menu(),
            reply_markup=
                await main_keyboard(),
            parse_mode=
                enums.ParseMode.HTML,
        )

    except Exception as e:

        LOGGER.exception(
            "Channel setup error: %s",
            e,
        )

        await message.reply_text(
            "❌ Channel set করা যায়নি।\n\n"
            "সঠিক @username অথবা Chat ID দিন।\n\n"
            f"<code>{str(e)[:500]}</code>",
            parse_mode=
                enums.ParseMode.HTML,
        )


# ============================================================
# MONGODB INDEXES
# ============================================================

async def create_indexes():

    try:

        await copy_col.create_index(
            [
                ("type", 1),
                ("job_key", 1),
            ],
            unique=True,
            name="copy_job_unique",
        )

    except Exception as e:

        LOGGER.debug(
            "copy_job_unique: %s",
            e,
        )

    try:

        await copy_col.create_index(
            [
                ("type", 1),
                ("file_unique_id", 1),
            ],
            name="file_unique_id_index",
        )

    except Exception as e:

        LOGGER.debug(
            "file_unique_id_index: %s",
            e,
        )

    try:

        await copy_col.create_index(
            [
                ("type", 1),
                ("status", 1),
            ],
            name="status_index",
        )

    except Exception as e:

        LOGGER.debug(
            "status_index: %s",
            e,
        )


# ============================================================
# INITIALIZATION
# ============================================================

async def initialize_copy_system():

    try:

        await create_indexes()

        await get_settings()

        LOGGER.info(
            "Channel Copy System initialized."
        )

    except Exception as e:

        LOGGER.exception(
            "Copy system initialization error: %s",
            e,
        )
