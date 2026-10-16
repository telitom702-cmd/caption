
import logging
import re
from datetime import datetime
from html import escape

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from plugins.database.database import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
LOGGER = logging.getLogger(__name__)

COLLECTION_NAME = "auto_cleaner"
CLEANER_STATE = {}

cleaner_col = db.db[COLLECTION_NAME]

DEFAULT_SETTINGS = {
    "_id": "settings",
    "enabled": False,
    "caption_cleaner": True,
    "remove_texts": [
        "[CineBari.com]",
        "MovieBaaz.com",
    ],
}


async def get_settings():
    try:
        data = await cleaner_col.find_one({"_id": "settings"})
        if not data:
            await cleaner_col.update_one(
                {"_id": "settings"},
                {"$setOnInsert": DEFAULT_SETTINGS},
                upsert=True,
            )
            data = await cleaner_col.find_one({"_id": "settings"})
        return data or DEFAULT_SETTINGS.copy()
    except Exception:
        LOGGER.exception("Failed to get cleaner settings")
        return DEFAULT_SETTINGS.copy()


async def update_settings(data):
    try:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$set": data},
            upsert=True,
        )
        return True
    except Exception:
        LOGGER.exception("Failed to update cleaner settings")
        return False


async def get_remove_texts():
    settings = await get_settings()
    return settings.get("remove_texts", [])


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
            {"_id": "settings"},
            {"$pull": {"remove_texts": text}},
        )
        return result.modified_count > 0
    except Exception:
        LOGGER.exception("Failed to delete remove text")
        return False


def clean_text(text, remove_texts):
    if not text:
        return ""

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


async def is_processed(chat_id, message_id):
    return await cleaner_col.find_one({
        "type": "processed",
        "chat_id": int(chat_id),
        "message_id": int(message_id),
    }) is not None


async def mark_processed(chat_id, message_id):
    await cleaner_col.update_one(
        {
            "type": "processed",
            "chat_id": int(chat_id),
            "message_id": int(message_id),
        },
        {
            "$set": {
                "type": "processed",
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "processed_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


async def process_caption(message):
    if not message.caption:
        return False

    new_caption = clean_text(
        message.caption, await get_remove_texts()
    )
    if new_caption == message.caption:
        return False

    try:
        await message.edit_caption(caption=new_caption)
        LOGGER.info(
            "Caption cleaned: chat=%s message=%s",
            message.chat.id, message.id,
        )
        return True
    except Exception:
        LOGGER.exception("Caption edit failed")
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


@Client.on_message(
    filters.channel & (filters.video | filters.document | filters.audio)
)
async def auto_cleaner_channel_handler(client, message):
    try:
        await process_message(message)
    except Exception:
        LOGGER.exception("Auto Cleaner error")


async def cleaner_menu():
    settings = await get_settings()
    status = "🟢 ON" if settings.get("enabled") else "🔴 OFF"
    caption_status = (
        "🟢 ON" if settings.get("caption_cleaner", True) else "🔴 OFF"
    )
    texts = settings.get("remove_texts", [])

    return (
        "🧹 <b>Auto Cleaner</b>\n\n"
        f"Status: <b>{status}</b>\n"
        f"Caption Cleaner: <b>{caption_status}</b>\n"
        f"Remove Texts: <b>{len(texts)}</b>"
    )


async def cleaner_keyboard():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🟢 Cleaner ON" if enabled else "🔴 Cleaner OFF",
            callback_data="ac_toggle",
        )],
        [InlineKeyboardButton(
            "🧹 Caption ON" if caption_enabled else "🚫 Caption OFF",
            callback_data="ac_caption",
        )],
        [
            InlineKeyboardButton("➕ Add Text", callback_data="ac_add"),
            InlineKeyboardButton("➖ Delete Text", callback_data="ac_delete"),
        ],
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="cc_add"),
            InlineKeyboardButton("📋 Channel List", callback_data="cc_list"),
        ],
        [InlineKeyboardButton("🧹 Clean Post", callback_data="cc_clean")],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="ac_refresh"),
            InlineKeyboardButton("❌ Close", callback_data="ac_close"),
        ],
    ])


@Client.on_message(filters.private & filters.command("cleaner"))
async def cleaner_command(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        await message.reply_text("You are not authorized to use this command.")
        return

    await message.reply_text(
        await cleaner_menu(),
        reply_markup=await cleaner_keyboard(),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^ac_"))
async def cleaner_callback(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return

    user_id = query.from_user.id
    data = query.data

    if data == "ac_close":
        CLEANER_STATE.pop(user_id, None)
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_reply_markup(reply_markup=None)
        return

    if data == "ac_toggle":
        settings = await get_settings()
        ok = await update_settings({
            "enabled": not settings.get("enabled", False)
        })
        await query.answer("Updated" if ok else "Database error",
                           show_alert=not ok)

    elif data == "ac_caption":
        settings = await get_settings()
        ok = await update_settings({
            "caption_cleaner": not settings.get("caption_cleaner", True)
        })
        await query.answer("Updated" if ok else "Database error",
                           show_alert=not ok)

    elif data == "ac_add":
        CLEANER_STATE[user_id] = "add_text"
        await query.message.edit_text(
            "📝 যে টেক্সটটি মুছতে চাও, সেটি পাঠাও।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="ac_refresh")
            ]]),
        )
        await query.answer()
        return

    elif data == "ac_delete":
        texts = await get_remove_texts()
        if not texts:
            await query.answer("List is empty!", show_alert=True)
            return

        buttons = [
            [InlineKeyboardButton(
                f"❌ {text[:30]}", callback_data=f"ac_del_{i}"
            )]
            for i, text in enumerate(texts)
        ]
        buttons.append([
            InlineKeyboardButton("🔙 Back", callback_data="ac_refresh")
        ])
        await query.message.edit_text(
            "🗑 Select text to delete:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        await query.answer()
        return

    elif data.startswith("ac_del_"):
        try:
            index = int(data.rsplit("_", 1)[1])
            texts = await get_remove_texts()
            if index < 0 or index >= len(texts):
                raise ValueError
            ok = await delete_remove_text(texts[index])
            await query.answer(
                "Deleted!" if ok else "Could not delete",
                show_alert=not ok,
            )
        except (ValueError, IndexError):
            await query.answer("Invalid selection!", show_alert=True)

    elif data == "ac_refresh":
        CLEANER_STATE.pop(user_id, None)
        await query.answer()

    try:
        await query.message.edit_text(
            await cleaner_menu(),
            reply_markup=await cleaner_keyboard(),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        LOGGER.debug("Menu did not need editing")


@Client.on_message(
    filters.private & filters.text
    & ~filters.command(["cancel", "start", "cleaner", "clean", "id", "stats"])
)
async def cleaner_text_input(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        return

    user_id = message.from_user.id
    if CLEANER_STATE.get(user_id) != "add_text":
        return

    value = message.text.strip()
    if not value:
        await message.reply_text("❌ Empty text is not allowed.")
        return

    ok = await add_remove_text(value)
    CLEANER_STATE.pop(user_id, None)

    if not ok:
        await message.reply_text("❌ Could not save text.")
        return

    await message.reply_text(
        f"✅ Added: <code>{escape(value)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    await message.reply_text(
        await cleaner_menu(),
        reply_markup=await cleaner_keyboard(),
        parse_mode=enums.ParseMode.HTML,
    )
