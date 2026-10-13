
# plugins/channel_copy_setting.py
# Source / Target Channel Management
# Numeric Chat ID ONLY
# © DramaZ.botz

import asyncio
import logging
import re
from datetime import datetime, timezone

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError

from info import ADMINS
from plugins.database.database import db

LOGGER = logging.getLogger(__name__)

COLLECTION = db.db["channel_copy"]
SETTINGS_ID = "copy_settings"

ADMIN_STATE = {}
DELETE_ALL_CONFIRM = set()


def clear_other_input_states(user_id):
    """Keep one admin text-input flow active across plugins."""
    cleared = False
    try:
        from plugins.auto_cleaner import CLEANER_STATE
        cleared = CLEANER_STATE.pop(user_id, None) is not None or cleared
    except ImportError:
        pass

    try:
        from plugins.channel_copy import ADMIN_STATE as COPY_ADMIN_STATE
        cleared = COPY_ADMIN_STATE.pop(user_id, None) is not None or cleared
    except ImportError:
        pass

    return cleared


DEFAULT_SETTINGS = {
    "enabled": False,
    "source_chat": None,
    "target_chat": None,
    "source_enabled": True,
    "target_enabled": True,
    "language": "both",
    "retry_delay": 30,
}

# --------------------------------------------------
# DATABASE
# --------------------------------------------------

async def get_settings():
    await COLLECTION.update_one(
        {"_id": SETTINGS_ID},
        {
            "$setOnInsert": {
                **DEFAULT_SETTINGS,
                "_id": SETTINGS_ID,
                "created_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    data = await COLLECTION.find_one({"_id": SETTINGS_ID})
    return data or {"_id": SETTINGS_ID, **DEFAULT_SETTINGS}


async def update_settings(values):
    values = dict(values)
    values["updated_at"] = datetime.now(timezone.utc)

    await COLLECTION.update_one(
        {"_id": SETTINGS_ID},
        {"$set": values},
        upsert=True,
    )


# --------------------------------------------------
# CHAT ID / PERMISSION VALIDATION
# --------------------------------------------------

def parse_channel_id(value):
    value = str(value or "").strip()

    # Accept numeric Telegram channel IDs only.
    # Do not accept @username or t.me links.
    if not re.fullmatch(r"-[0-9]+", value):
        raise ValueError(
            "শুধু Numeric Channel / Group ID দিন। উদাহরণ: -1001234567890"
        )

    return int(value)


async def validate_channel(client, channel_id, role):
    chat = await client.get_chat(channel_id)

    if chat.type not in (
        enums.ChatType.CHANNEL,
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ):
        raise ValueError("এই Chat ID-টি Telegram Channel / Group নয়।")

    me = await client.get_me()
    member = await client.get_chat_member(chat.id, me.id)

    allowed_statuses = {
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    }

    if member.status not in allowed_statuses:
        raise ValueError(
            "বট এই Channel / Group-এর Administrator নয়। "
            "আগে বটকে Admin হিসেবে যোগ করুন।"
        )

    # Channels need post permission; group administrators can send messages.
    if role == "target" and chat.type == enums.ChatType.CHANNEL:
        if member.status != enums.ChatMemberStatus.OWNER:
            if not getattr(member, "privileges", None):
                raise ValueError("Target Channel / Group-এর Admin Permission যাচাই করা যায়নি।")

            if not getattr(member.privileges, "can_post_messages", False):
                raise ValueError(
                    "Target Channel-এ বটের Post Messages Permission নেই।"
                )

    return chat


# --------------------------------------------------
# KEYBOARDS
# --------------------------------------------------

async def main_keyboard():
    s = await get_settings()

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                ("📥 Source: ON" if s.get("source_enabled", True)
                 else "📥 Source: OFF"),
                callback_data="ccs_source_toggle",
            ),
            InlineKeyboardButton(
                ("📤 Target: ON" if s.get("target_enabled", True)
                 else "📤 Target: OFF"),
                callback_data="ccs_target_toggle",
            ),
        ],
        [
            InlineKeyboardButton("➕ Add Source", callback_data="ccs_add_source"),
            InlineKeyboardButton("➕ Add Target", callback_data="ccs_add_target"),
        ],
        [
            InlineKeyboardButton("🔄 Change Source", callback_data="ccs_change_source"),
            InlineKeyboardButton("🔄 Change Target", callback_data="ccs_change_target"),
        ],
        [
            InlineKeyboardButton("🗑️ Delete Source", callback_data="ccs_delete_source"),
            InlineKeyboardButton("🗑️ Delete Target", callback_data="ccs_delete_target"),
        ],
        [
            InlineKeyboardButton("🧹 Delete All Data", callback_data="ccs_delete_all"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="ccs_refresh"),
            InlineKeyboardButton("❌ Close", callback_data="ccs_close"),
        ],
        [
            InlineKeyboardButton("🔙 Back to /copy", callback_data="cc_back_main"),
        ],
    ])


async def menu_text():
    s = await get_settings()

    return (
        "⚙️ <b>CHANNEL COPY MANAGEMENT</b>\n\n"
        f"📥 Source: {'🟢 ON' if s.get('source_enabled', True) else '🔴 OFF'}\n"
        f"<code>{s.get('source_chat') or 'Not Set'}</code>\n\n"
        f"📤 Target: {'🟢 ON' if s.get('target_enabled', True) else '🔴 OFF'}\n"
        f"<code>{s.get('target_chat') or 'Not Set'}</code>\n\n"
        f"▶️ Copy System: {'🟢 ON' if s.get('enabled') else '🔴 OFF'}\n\n"
        "🔐 শুধু Numeric Chat ID গ্রহণ করা হয়।"
    )


async def show_menu(message):
    from plugins.channel_copy import main_menu as copy_menu, main_keyboard as copy_keyboard

    await message.reply_text(
        await copy_menu(),
        reply_markup=await copy_keyboard(),
        parse_mode=enums.ParseMode.HTML,
    )


# --------------------------------------------------
# COMMAND
# --------------------------------------------------

@Client.on_message(filters.private & filters.command("copysetting"))
async def copy_setting_command(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        await message.reply_text("এই কমান্ডটি শুধু bot admin ব্যবহার করতে পারবেন।")
        return

    await message.reply_text(
        "Channel ID settings এখন /copy menu-এর ভিতরে আছে। "
        "/copy পাঠিয়ে “Channel IDs” চাপুন।"
    )


# --------------------------------------------------
# CALLBACKS
# --------------------------------------------------

@Client.on_callback_query(filters.regex(r"^ccs_"))
async def copy_setting_callback(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return

    data = query.data
    uid = query.from_user.id

    if data in ("ccs_add_source", "ccs_change_source"):
        clear_other_input_states(uid)
        ADMIN_STATE[uid] = "source"
        await query.message.edit_text(
            "📥 <b>Set Source Channel / Group</b>\n\n"
            "শুধু Numeric Chat ID পাঠান।\n"
            "উদাহরণ: <code>-1001234567890</code>\n\n"
            "/cancel দিয়ে বাতিল করতে পারবেন।",
            parse_mode=enums.ParseMode.HTML,
        )
        await query.answer()
        return

    if data in ("ccs_add_target", "ccs_change_target"):
        clear_other_input_states(uid)
        ADMIN_STATE[uid] = "target"
        await query.message.edit_text(
            "📤 <b>Set Target Channel / Group</b>\n\n"
            "শুধু Numeric Chat ID পাঠান।\n"
            "উদাহরণ: <code>-1001234567890</code>\n\n"
            "/cancel দিয়ে বাতিল করতে পারবেন।",
            parse_mode=enums.ParseMode.HTML,
        )
        await query.answer()
        return

    if data == "ccs_source_toggle":
        s = await get_settings()
        await update_settings({
            "source_enabled": not s.get("source_enabled", True)
        })

    elif data == "ccs_target_toggle":
        s = await get_settings()
        await update_settings({
            "target_enabled": not s.get("target_enabled", True)
        })

    elif data == "ccs_delete_source":
        await update_settings({
            "source_chat": None,
            "source_enabled": True,
        })
        await query.answer("Source Channel deleted")

    elif data == "ccs_delete_target":
        await update_settings({
            "target_chat": None,
            "target_enabled": True,
        })
        await query.answer("Target Channel deleted")

    elif data == "ccs_delete_all":
        DELETE_ALL_CONFIRM.add(uid)
        await query.message.edit_text(
            "⚠️ <b>Delete All Data?</b>\n\n"
            "এতে Copy Jobs, Target File Index এবং "
            "Source Duplicate History মুছে যাবে।\n\n"
            "Source/Target Channel ID ও ON/OFF Settings "
            "মুছে যাবে না।",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Confirm Delete",
                        callback_data="ccs_confirm_delete_all",
                    ),
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="ccs_cancel_delete_all",
                    ),
                ]
            ]),
            parse_mode=enums.ParseMode.HTML,
        )
        await query.answer()
        return

    elif data == "ccs_confirm_delete_all":
        if uid not in DELETE_ALL_CONFIRM:
            await query.answer("আগে Delete All নির্বাচন করুন।", show_alert=True)
            return

        DELETE_ALL_CONFIRM.discard(uid)

        result = await COLLECTION.delete_many({
            "type": {"$in": ["copy_job", "target_file", "source_seen"]}
        })

        await query.answer(
            f"Deleted: {result.deleted_count}",
            show_alert=True,
        )

    elif data == "ccs_cancel_delete_all":
        DELETE_ALL_CONFIRM.discard(uid)

    elif data == "ccs_refresh":
        pass

    elif data == "ccs_close":
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
    except RPCError:
        pass

    if data not in ("ccs_delete_source", "ccs_delete_target",
                    "ccs_confirm_delete_all", "ccs_cancel_delete_all"):
        await query.answer("Settings updated")


# --------------------------------------------------
# ADMIN CHAT ID INPUT
# --------------------------------------------------

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.command([
        "cancel", "start", "sourcedupe", "copysetting", "copy",
        "cleaner", "id", "stats",
    ]),
    group=11,
)
async def copy_setting_input(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        return

    uid = message.from_user.id
    role = ADMIN_STATE.get(uid)

    if role not in ("source", "target"):
        return

    value = message.text.strip()

    try:
        channel_id = parse_channel_id(value)
        chat = await validate_channel(client, channel_id, role)

        field = "source_chat" if role == "source" else "target_chat"

        await update_settings({field: int(chat.id)})
        ADMIN_STATE.pop(uid, None)

        await message.reply_text(
            f"✅ <b>{'Source' if role == 'source' else 'Target'} Channel Saved</b>\n\n"
            f"📌 {chat.title}\n"
            f"🆔 <code>{chat.id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

        await show_menu(message)

    except Exception as e:
        LOGGER.warning("Channel setup failed: %s", e)
        await message.reply_text(
            "❌ Channel সেট করা যায়নি।\n\n"
            f"<code>{str(e)[:500]}</code>\n\n"
            "শুধু সঠিক Numeric Chat ID দিন।",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.private & filters.command("cancel"))
async def copy_setting_cancel(client, message):
    if not message.from_user:
        return

    if message.from_user.id not in ADMINS:
        return

    user_id = message.from_user.id
    had_active_state = ADMIN_STATE.pop(user_id, None) is not None
    had_active_state = user_id in DELETE_ALL_CONFIRM or had_active_state
    DELETE_ALL_CONFIRM.discard(user_id)
    had_active_state = clear_other_input_states(user_id) or had_active_state

    if had_active_state:
        await message.reply_text("❌ চলমান সেটআপ বাতিল করা হয়েছে।")
    else:
        await message.reply_text("ℹ️ বাতিল করার মতো কোনো চলমান সেটআপ নেই।")


async def initialize_channel_copy_settings():
    await get_settings()
    LOGGER.info("Channel copy settings initialized.")
