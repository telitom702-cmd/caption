
# plugins/source_duplicate_check.py
# Source Channel Duplicate Protection
# © DramaZ.botz

import logging
from datetime import datetime, timezone

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from plugins.database.database import db

LOGGER = logging.getLogger(__name__)

COLLECTION = db.db["channel_copy"]
SETTINGS_ID = "source_duplicate_settings"


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

async def get_source_duplicate_settings():
    await COLLECTION.update_one(
        {"_id": SETTINGS_ID},
        {
            "$setOnInsert": {
                "enabled": True,
                "created_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    data = await COLLECTION.find_one({"_id": SETTINGS_ID})

    if not data:
        return {"enabled": True}

    return data


async def set_source_duplicate_enabled(enabled):
    await COLLECTION.update_one(
        {"_id": SETTINGS_ID},
        {
            "$set": {
                "enabled": bool(enabled),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


# --------------------------------------------------
# MEDIA HELPERS
# --------------------------------------------------

def get_media_info(message):
    media = (
        message.photo
        or message.video
        or message.document
        or message.audio
        or message.animation
        or message.voice
    )

    if not media:
        return None

    filename = ""

    if message.document:
        filename = message.document.file_name or ""
    elif message.video:
        filename = message.video.file_name or ""
    elif message.audio:
        filename = message.audio.file_name or ""
    elif message.animation:
        filename = message.animation.file_name or ""
    elif message.photo:
        filename = "photo"

    return {
        "file_unique_id": getattr(media, "file_unique_id", None),
        "filename": filename,
        "file_size": int(getattr(media, "file_size", 0) or 0),
    }


def normalize_filename(filename):
    # Match the normalization used by the original copy system.
    import re

    filename = (filename or "").lower()

    filename = re.sub(
        r"\.(mkv|mp4|avi|mov|wmv|flv|webm|mp3|m4a|aac|flac|zip|rar|7z)$",
        "",
        filename,
        flags=re.IGNORECASE,
    )

    filename = re.sub(r"[\W_]+", "", filename)

    return filename.strip()


# --------------------------------------------------
# SOURCE DUPLICATE CHECK
# --------------------------------------------------

async def is_source_duplicate(message):
    settings = await get_source_duplicate_settings()

    if not settings.get("enabled", True):
        return False

    info = get_media_info(message)

    if not info:
        return False

    source_chat = int(message.chat.id)
    conditions = []

    unique_id = info["file_unique_id"]

    if unique_id:
        conditions.append({
            "file_unique_id": unique_id,
        })

    filename = normalize_filename(info["filename"])
    size = info["file_size"]

    if filename and size:
        conditions.append({
            "normalized_filename": filename,
            "file_size": size,
        })

    if not conditions:
        return False

    found = await COLLECTION.find_one({
        "type": "source_seen",
        "source_chat": source_chat,
        "$or": conditions,
    })

    return found is not None


# --------------------------------------------------
# MARK SOURCE FILE AS PROCESSED
# --------------------------------------------------

async def mark_source_processed(message):
    """
    Call after a successful copy, or when the Target
    duplicate check confirms the file is already present.
    """
    info = get_media_info(message)

    if not info:
        return False

    unique_id = info["file_unique_id"]
    filename = normalize_filename(info["filename"])
    size = info["file_size"]

    if not unique_id and not (filename and size):
        return False

    source_chat = int(message.chat.id)

    # Avoid creating duplicate records for a previously
    # indexed file with the same unique ID.
    query = {
        "type": "source_seen",
        "source_chat": source_chat,
    }

    if unique_id:
        query["file_unique_id"] = unique_id
    else:
        query["normalized_filename"] = filename
        query["file_size"] = size

    await COLLECTION.update_one(
        query,
        {
            "$set": {
                "type": "source_seen",
                "source_chat": source_chat,
                "source_message_id": int(message.id),
                "file_unique_id": unique_id,
                "normalized_filename": filename,
                "file_size": size,
                "processed_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    return True


# --------------------------------------------------
# ADMIN SETTINGS MENU
# --------------------------------------------------

async def source_duplicate_keyboard():
    settings = await get_source_duplicate_settings()
    enabled = settings.get("enabled", True)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔴 Turn OFF" if enabled else "🟢 Turn ON",
                callback_data="sdc_toggle",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="sdc_refresh",
            ),
            InlineKeyboardButton(
                "❌ Close",
                callback_data="sdc_close",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 Back to /copy",
                callback_data="cc_back_main",
            ),
        ],
    ])


async def source_duplicate_text():
    settings = await get_source_duplicate_settings()

    enabled = settings.get("enabled", True)

    return (
        "🛡️ <b>SOURCE DUPLICATE CHECK</b>\n\n"
        f"Status: {'🟢 ON' if enabled else '🔴 OFF'}\n\n"
        "🔎 File Unique ID Check\n"
        "📁 Filename + File Size Check\n"
        "💾 MongoDB History\n\n"
        "ON: আগে প্রসেস করা Media Skip হবে।\n"
        "OFF: Source Duplicate Check বন্ধ থাকবে।\n\n"
        "Target Duplicate Protection আলাদা থাকবে।"
    )


@Client.on_message(
    filters.private & filters.command("sourcedupe")
)
async def source_duplicate_command(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        await message.reply_text("এই কমান্ডটি শুধু bot admin ব্যবহার করতে পারবেন।")
        return

    await message.reply_text(
        "Source duplicate settings এখন /copy menu-এর ভিতরে আছে। "
        "/copy পাঠিয়ে “Duplicate Check” চাপুন।"
    )


@Client.on_callback_query(filters.regex(r"^sdc_"))
async def source_duplicate_callback(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return

    if query.data == "sdc_toggle":
        settings = await get_source_duplicate_settings()

        await set_source_duplicate_enabled(
            not settings.get("enabled", True)
        )

    elif query.data == "sdc_close":
        await query.answer("Closed")
        await query.message.delete()
        return

    try:
        from plugins.channel_copy import main_menu as copy_menu, main_keyboard as copy_keyboard
        await query.message.edit_text(
            await copy_menu(),
            reply_markup=await copy_keyboard(),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await query.answer("Source duplicate settings updated")


async def initialize_source_duplicate_check():
    await get_source_duplicate_settings()
    LOGGER.info("Source duplicate check initialized.")
