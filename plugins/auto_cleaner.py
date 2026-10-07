import logging
import re
from datetime import datetime

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS

# ডিবাগ লগিং সিস্টেম মুছে ফেলা হয়েছে, শুধুমাত্র লগার নেওয়া হয়েছে
LOGGER = logging.getLogger(__name__)

# সমস্যা ১: ইম্পোর্ট পাথ ঠিক করা হয়েছে 
# যদি আপনার database.py ফাইলটি plugins/ ফোল্ডারে থাকে, তবে নিচের লাইনটি ব্যবহার করুন:
from plugins.database import db
# যদি আলাদা ফোল্ডার থাকে (plugins/database/database.py), তবে: from plugins.database.database import db

COLLECTION_NAME = "auto_cleaner"
CLEANER_STATE = {}

try:
    cleaner_col = db.db[COLLECTION_NAME]
    LOGGER.info("Database collection initialized successfully.")
except Exception as e:
    LOGGER.error("Failed to initialize database collection: %s", e)

DEFAULT_SETTINGS = {
    "_id": "settings",
    "enabled": False,
    "caption_cleaner": True,
    "remove_texts": [
        "[CineBari.com]",
        "MovieBaaz.com"
    ],
}


async def get_settings():
    LOGGER.debug("Fetching settings from DB...")
    try:
        data = await cleaner_col.find_one({"_id": "settings"})
        if not data:
            LOGGER.info("No settings found, inserting default settings.")
            data = DEFAULT_SETTINGS.copy()
            await cleaner_col.insert_one(data.copy())
            return data
        
        LOGGER.debug("Settings fetched successfully.")
        return data
    except Exception as e:
        LOGGER.error("Error in get_settings: %s", e)
        return DEFAULT_SETTINGS


async def update_settings(data):
    try:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$set": data},
            upsert=True
        )
        LOGGER.info("Settings updated successfully.")
    except Exception as e:
        LOGGER.error("Error in update_settings: %s", e)


async def is_enabled():
    settings = await get_settings()
    return bool(settings.get("enabled", False))


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
            upsert=True
        )
        return True
    except Exception as e:
        LOGGER.error("Error in add_remove_text: %s", e)
        return False


async def delete_remove_text(text):
    try:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$pull": {"remove_texts": text}}
        )
    except Exception as e:
        LOGGER.error("Error in delete_remove_text: %s", e)


def clean_text(text, remove_texts):
    if not text:
        return ""
    result = text
    for remove_text in remove_texts:
        if not remove_text:
            continue
        result = re.sub(re.escape(remove_text), "", result, flags=re.IGNORECASE)
    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"^[\s\-_:|]+$", "", result, flags=re.MULTILINE)
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    result = "\n".join(lines)
    return result.strip()


async def is_processed(chat_id, message_id):
    try:
        data = await cleaner_col.find_one(
            {"type": "processed", "chat_id": int(chat_id), "message_id": int(message_id)}
        )
        return bool(data)
    except Exception as e:
        LOGGER.error("Error in is_processed: %s", e)
        return False


async def mark_processed(chat_id, message_id):
    try:
        await cleaner_col.update_one(
            {"type": "processed", "chat_id": int(chat_id), "message_id": int(message_id)},
            {"$set": {
                "type": "processed", "chat_id": int(chat_id), 
                "message_id": int(message_id), "processed_at": datetime.utcnow()
            }},
            upsert=True
        )
    except Exception as e:
        LOGGER.error("Error in mark_processed: %s", e)


async def process_caption(message):
    if not message.caption:
        return False
    remove_texts = await get_remove_texts()
    if not remove_texts:
        return False

    old_caption = message.caption
    new_caption = clean_text(old_caption, remove_texts)

    if new_caption == old_caption:
        return False

    try:
        await message.edit_caption(caption=new_caption)
        LOGGER.info("Caption cleaned | chat=%s | message=%s", message.chat.id, message.id)
        return True
    except Exception as e:
        LOGGER.error("Caption edit failed | chat=%s | message=%s | error=%s", message.chat.id, message.id, e)
        return False


async def process_message(message):
    if not await is_enabled():
        LOGGER.debug("Cleaner is disabled. Skipping message.")
        return

    if await is_processed(message.chat.id, message.id):
        LOGGER.debug("Message already processed.")
        return

    if not (message.video or message.document or message.audio):
        return

    settings = await get_settings()
    caption_enabled = settings.get("caption_cleaner", True)

    if caption_enabled:
        await process_caption(message)

    await mark_processed(message.chat.id, message.id)


@Client.on_message(
    filters.channel & (filters.video | filters.document | filters.audio)
)
async def auto_cleaner_channel_handler(client, message):
    LOGGER.debug("Received media in channel: chat=%s msg=%s", message.chat.id, message.id)
    try:
        await process_message(message)
    except Exception as e:
        LOGGER.exception("Auto Cleaner error: %s", e)


async def cleaner_menu():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)
    texts = settings.get("remove_texts", [])
    
    status = "🟢 ON" if enabled else "🔴 OFF"
    caption_status = "🟢 ON" if caption_enabled else "🔴 OFF"
    
    return (
        f"🧹 <b>Auto Cleaner</b>\n\n"
        f"Status: <b>{status}</b>\n"
        f"Caption Cleaner: <b>{caption_status}</b>\n"
        f"Remove Texts: <b>{len(texts)}</b>"
    )


async def cleaner_keyboard():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Cleaner ON" if enabled else "🔴 Cleaner OFF", callback_data="ac_toggle")],
        [InlineKeyboardButton("🧹 Caption ON" if caption_enabled else "🚫 Caption OFF", callback_data="ac_caption")],
        [InlineKeyboardButton("➕ Add Text", callback_data="ac_add"), InlineKeyboardButton("➖ Delete Text", callback_data="ac_delete")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="ac_refresh")]
    ])


@Client.on_message(filters.private & filters.command("cleaner"))
async def cleaner_command(client, message):
    LOGGER.info("'/cleaner' command received from user: %s", message.from_user.id)
    
    if message.from_user.id not in ADMINS:
        LOGGER.warning("Unauthorized access to /cleaner by: %s", message.from_user.id)
        await message.reply_text("You are not authorized to use this command.")
        return

    try:
        await message.reply_text(
            await cleaner_menu(),
            reply_markup=await cleaner_keyboard(),
            parse_mode=enums.ParseMode.HTML
        )
        LOGGER.info("Cleaner menu sent successfully.")
    except Exception as e:
        LOGGER.error("Failed to send cleaner menu: %s", e)


@Client.on_callback_query(filters.regex(r"^ac_"))
async def cleaner_callback(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return

    user_id = query.from_user.id
    data = query.data

    if data == "ac_toggle":
        settings = await get_settings()
        await update_settings({"enabled": not settings.get("enabled", False)})
        await query.answer("Toggled!")
        LOGGER.info("Cleaner toggled by %s", user_id)

    elif data == "ac_caption":
        settings = await get_settings()
        await update_settings({"caption_cleaner": not settings.get("caption_cleaner", True)})
        await query.answer("Toggled!")

    elif data == "ac_add":
        CLEANER_STATE[user_id] = "add"
        await query.message.edit_text("📝 Send the text you want to remove.")
        await query.answer()
        return

    elif data == "ac_delete":
        texts = await get_remove_texts()
        if not texts:
            await query.answer("List is empty!", show_alert=True)
            return
        
        buttons = [[InlineKeyboardButton(f"❌ {text[:30]}", callback_data=f"ac_del_{i}")] for i, text in enumerate(texts)]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="ac_refresh")])
        
        await query.message.edit_text("🗑 Select text to delete:", reply_markup=InlineKeyboardMarkup(buttons))
        await query.answer()
        return

    elif data.startswith("ac_del_"):
        try:
            index = int(data.split("_")[-1])
        except ValueError:
            await query.answer("Invalid selection!", show_alert=True)
            return
        
        texts = await get_remove_texts()
        if 0 <= index < len(texts):
            await delete_remove_text(texts[index])
            await query.answer("Deleted!")
        else:
            await query.answer("Not found!", show_alert=True)

    elif data == "ac_refresh":
        await query.answer()

    try:
        await query.message.edit_text(
            await cleaner_menu(),
            reply_markup=await cleaner_keyboard(),
            parse_mode=enums.ParseMode.HTML
        )
    except Exception:
        pass


@Client.on_message(
    filters.private
    & filters.text
    & ~filters.command(["cancel", "start", "cleaner", "id", "stats"])
)
async def cleaner_text_input(client, message):
    if message.from_user.id not in ADMINS:
        return

    user_id = message.from_user.id
    LOGGER.debug("Text input received from admin %s: %s", user_id, message.text)

    if CLEANER_STATE.get(user_id) != "add":
        LOGGER.debug("User not in add state. Ignoring text input.")
        return

    value = message.text.strip()
    if not value:
        await message.reply_text("❌ Empty text is not allowed.")
        return

    success = await add_remove_text(value)
    if success:
        LOGGER.info("Text added by %s: %s", user_id, value)
    
    CLEANER_STATE.pop(user_id, None)

    await message.reply_text(
        f"✅ Added: <code>{value}</code>",
        parse_mode=enums.ParseMode.HTML
    )
    await message.reply_text(
        await cleaner_menu(),
        reply_markup=await cleaner_keyboard(),
        parse_mode=enums.ParseMode.HTML
    )
