import re
import logging
from datetime import datetime

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from plugins.database.database import db
from info import ADMINS

LOGGER = logging.getLogger(__name__)

COLLECTION_NAME = "auto_cleaner"
CLEANER_STATE = {}
cleaner_col = db.db[COLLECTION_NAME]

DEFAULT_SETTINGS = {
    "_id": "settings",
    "enabled": False,
    "caption_cleaner": True,
    "remove_texts": ["[CineBari.com]", "MovieBaaz.com"],
    "channels": {},
}

async def get_settings():
    data = await cleaner_col.find_one({"_id": "settings"})
    if not data:
        await cleaner_col.insert_one(DEFAULT_SETTINGS.copy())
        return DEFAULT_SETTINGS.copy()
    return data

async def update_settings(data):
    await cleaner_col.update_one({"_id": "settings"}, {"$set": data}, upsert=True)

async def is_enabled():
    settings = await get_settings()
    return bool(settings.get("enabled", False))

async def get_remove_texts():
    settings = await get_settings()
    return settings.get("remove_texts", [])

async def add_remove_text(text):
    text = text.strip()
    if not text: return False
    await cleaner_col.update_one({"_id": "settings"}, {"$addToSet": {"remove_texts": text}}, upsert=True)
    return True

async def delete_remove_text(text):
    await cleaner_col.update_one({"_id": "settings"}, {"$pull": {"remove_texts": text}})

def clean_text(text, remove_texts):
    if not text: return ""
    result = text
    for remove_text in remove_texts:
        if not remove_text: continue
        result = re.sub(re.escape(remove_text), "", result, flags=re.IGNORECASE)
    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"^[\s\-_:|]+$", "", result, flags=re.MULTILINE)
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    result = "\n".join(lines)
    return result.strip()

async def is_processed(chat_id, message_id):
    data = await cleaner_col.find_one({"type": "processed", "chat_id": int(chat_id), "message_id": int(message_id)})
    return bool(data)

async def mark_processed(chat_id, message_id):
    await cleaner_col.update_one(
        {"type": "processed", "chat_id": int(chat_id), "message_id": int(message_id)},
        {"$set": {"type": "processed", "chat_id": int(chat_id), "message_id": int(message_id), "processed_at": datetime.utcnow()}},
        upsert=True,
    )

async def process_caption(message):
    if not message.caption: return False
    remove_texts = await get_remove_texts()
    if not remove_texts: return False
    
    old_caption = message.caption
    new_caption = clean_text(old_caption, remove_texts)
    
    if new_caption == old_caption: return False
    
    try:
        await message.edit_caption(caption=new_caption)
        LOGGER.info("Caption cleaned | chat=%s | message=%s", message.chat.id, message.id)
        return True
    except Exception as e:
        LOGGER.error("Caption edit failed: %s", e)
        return False

async def process_message(message):
    if not await is_enabled(): return
    if await is_processed(message.chat.id, message.id): return
    if not (message.video or message.document or message.audio): return
    
    if await get_settings().get("caption_cleaner", True):
        await process_caption(message)
        
    await mark_processed(message.chat.id, message.id)

@Client.on_message(filters.channel & (filters.video | filters.document | filters.audio))
async def auto_cleaner_channel_handler(client, message):
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
        f"Remove Texts: <b>{len(texts)}</b>\n"
    )

async def cleaner_keyboard():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Cleaner ON" if enabled else "🔴 Cleaner OFF", callback_data="ac_toggle")],
        [InlineKeyboardButton("🧹 Caption ON" if caption_enabled else "🚫 Caption OFF", callback_data="ac_caption")],
        [InlineKeyboardButton("➕ Add Text", callback_data="ac_add"), InlineKeyboardButton("➖ Delete Text", callback_data="ac_delete")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="ac_refresh")],
    ])

@Client.on_message(filters.private & filters.command("cleaner"))
async def cleaner_command(client, message):
    if message.from_user.id not in ADMINS: return
    await message.reply_text(await cleaner_menu(), reply_markup=await cleaner_keyboard(), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^ac_"))
async def cleaner_callback(client, query):
    if query.from_user.id not in ADMINS:
        return await query.answer("Admins only!", show_alert=True)
    
    user_id = query.from_user.id
    data = query.data

    if data == "ac_toggle":
        settings = await get_settings()
        await update_settings({"enabled": not settings.get("enabled", False)})
        await query.answer("Toggled")
    elif data == "ac_caption":
        settings = await get_settings()
        await update_settings({"caption_cleaner": not settings.get("caption_cleaner", True)})
        await query.answer("Toggled")
    elif data == "ac_add":
        CLEANER_STATE[user_id] = "add"
        await query.message.edit_text("Send the text to remove now.")
        return
    elif data == "ac_delete":
        texts = await get_remove_texts()
        if not texts:
            await query.answer("List empty!", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(f"❌ {t[:30]}", callback_data=f"ac_del_{i}")] for i, t in enumerate(texts)]
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="ac_refresh")])
        await query.message.edit_text("Select to delete:", reply_markup=InlineKeyboardMarkup(buttons))
        return
    elif data.startswith("ac_del_"):
        index = int(data.split("_")[-1])
        texts = await get_remove_texts()
        if index < len(texts):
            await delete_remove_text(texts[index])
            await query.answer("Deleted!")
    elif data == "ac_refresh":
        await query.answer()

    try:
        await query.message.edit_text(await cleaner_menu(), reply_markup=await cleaner_keyboard(), parse_mode=enums.ParseMode.HTML)
    except: pass

@Client.on_message(filters.private & filters.text & ~filters.command(["cancel", "start", "cleaner"]))
async def cleaner_text_input(client, message):
    if message.from_user.id not in ADMINS: return
    user_id = message.from_user.id
    if CLEANER_STATE.get(user_id) == "add":
        value = message.text.strip()
        if value:
            await add_remove_text(value)
            CLEANER_STATE.pop(user_id, None)
            await message.reply_text(f"✅ Added: <code>{value}</code>", parse_mode=enums.ParseMode.HTML)
