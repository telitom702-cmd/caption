
# plugins/auto_cleaner_channels.py
# Auto Cleaner Channel / Group Management
# Add by Chat ID with Added / Cancel confirmation

import logging
from html import escape

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError

from info import ADMINS
from plugins.database.database import db

LOG = logging.getLogger(__name__)

COL = db.db["auto_cleaner_channels"]
LIMIT = 8

# Admin ID -> None (waiting for ID) or Chat ID (waiting for confirmation)
PENDING_CHAT_ID = {}


def kb(rows):
    return InlineKeyboardMarkup(rows)


def home_kb():
    return kb([
        [
            InlineKeyboardButton(
                "➕ Add by Chat ID",
                callback_data="acs_add_id",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 My Channels",
                callback_data="acs_saved_0",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="acs_home",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Main Cleaner",
                callback_data="acs_main",
            )
        ],
    ])


async def home_text():
    total = await COL.count_documents({})
    active = await COL.count_documents({"enabled": True})

    return (
        "📢 <b>Channel / Group Settings</b>\n\n"
        f"Saved Chats: <b>{total}</b>\n"
        f"Cleaner ON: <b>{active}</b>\n\n"
        "➕ Add by Chat ID চাপুন এবং ID দিন।"
    )


def is_bot_admin(status):
    return status in (
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    )


async def build_saved_list(page=0):
    docs = (
        await COL.find({})
        .sort("title", 1)
        .to_list(length=10000)
    )

    total = len(docs)
    start = page * LIMIT
    items = docs[start:start + LIMIT]
    rows = []

    for doc in items:
        cid = int(doc["_id"])
        title = doc.get("title", "Chat")
        enabled = bool(doc.get("enabled", False))

        rows.append([
            InlineKeyboardButton(
                f"{'🟢' if enabled else '🔴'} {title}"[:60],
                callback_data=f"acs_detail_{cid}",
            )
        ])

        rows.append([
            InlineKeyboardButton(
                f"🆔 {cid}",
                callback_data=f"acs_detail_{cid}",
            )
        ])

    if not rows:
        rows.append([
            InlineKeyboardButton(
                "কোনো সেভ করা চ্যাট নেই",
                callback_data="acs_noop",
            )
        ])

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ Previous",
                callback_data=f"acs_saved_{page - 1}",
            )
        )

    if start + LIMIT < total:
        nav.append(
            InlineKeyboardButton(
                "Next ➡️",
                callback_data=f"acs_saved_{page + 1}",
            )
        )

    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton(
            "➕ Add by ID",
            callback_data="acs_add_id",
        ),
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="acs_home",
        ),
    ])

    return kb(rows), total


def detail_kb(cid, enabled):
    return kb([
        [
            InlineKeyboardButton(
                "🔴 Turn OFF" if enabled else "🟢 Turn ON",
                callback_data=f"acs_toggle_{cid}",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"acs_delete_{cid}",
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Add Another",
                callback_data="acs_add_id",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data="acs_saved_0",
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="acs_home",
            ),
        ],
    ])


# --------------------------------------------------
# Receive Chat ID
# --------------------------------------------------

@Client.on_message(
    filters.private & filters.user(ADMINS) & filters.text,
    group=-1,
)
async def receive_chat_id(client, message):
    uid = message.from_user.id

    if uid not in PENDING_CHAT_ID:
        return

    raw = message.text.strip()

    if raw.lower() in ("/cancel", "cancel"):
        PENDING_CHAT_ID.pop(uid, None)

        return await message.reply_text(
            "❌ Add Channel / Group বাতিল করা হয়েছে।",
            reply_markup=kb([
                [
                    InlineKeyboardButton(
                        "🔙 Settings",
                        callback_data="acs_home",
                    )
                ]
            ]),
        )

    # Only accept a numeric Chat ID
    try:
        cid = int(raw)
    except ValueError:
        return await message.reply_text(
            "❌ সঠিক Numeric Chat ID পাঠান।\n\n"
            "উদাহরণ: <code>-1001234567890</code>\n"
            "বাতিল করতে /cancel পাঠান।",
            parse_mode=enums.ParseMode.HTML,
        )

    if cid >= 0:
        return await message.reply_text(
            "❌ সঠিক Channel / Group ID দিন।\n"
            "সাধারণত ID ঋণাত্মক হয়, যেমন <code>-1001234567890</code>।",
            parse_mode=enums.ParseMode.HTML,
        )

    # Store ID temporarily; do not save it yet
    PENDING_CHAT_ID[uid] = cid

    await message.reply_text(
        "🆔 <b>Chat ID Received</b>\n\n"
        f"ID: <code>{cid}</code>\n\n"
        "এখন Added চাপলে যাচাই করে সেভ হবে।",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=kb([
            [
                InlineKeyboardButton(
                    "✅ Added",
                    callback_data="acs_confirm_add",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="acs_cancel_add",
                ),
            ]
        ]),
    )


# --------------------------------------------------
# Callback Handler
# --------------------------------------------------

@Client.on_callback_query(filters.regex(r"^acs_"))
async def channel_settings_callback(client, query):
    if not query.from_user or query.from_user.id not in ADMINS:
        return await query.answer(
            "Admins only!",
            show_alert=True,
        )

    data = query.data
    uid = query.from_user.id

    try:
        # Home
        if data == "acs_home":
            PENDING_CHAT_ID.pop(uid, None)

            await query.message.edit_text(
                await home_text(),
                reply_markup=home_kb(),
                parse_mode=enums.ParseMode.HTML,
            )
            return await query.answer()

        # Main Cleaner
        if data == "acs_main":
            PENDING_CHAT_ID.pop(uid, None)

            from plugins.auto_cleaner import (
                cleaner_menu,
                cleaner_keyboard,
            )

            await query.message.edit_text(
                await cleaner_menu(),
                reply_markup=await cleaner_keyboard(),
                parse_mode=enums.ParseMode.HTML,
            )
            return await query.answer()

        # Start adding a chat
        if data == "acs_add_id":
            PENDING_CHAT_ID[uid] = None

            await query.message.edit_text(
                "➕ <b>Add Channel / Group by ID</b>\n\n"
                "আপনার Channel / Group-এর numeric Chat ID পাঠান।\n\n"
                "উদাহরণ: <code>-1001234567890</code>\n\n"
                "ID পাঠানোর পর Added অথবা Cancel বাটন আসবে।",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=kb([
                    [
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data="acs_cancel_add",
                        )
                    ]
                ]),
            )
            return await query.answer()

        # Cancel adding a chat
        if data == "acs_cancel_add":
            PENDING_CHAT_ID.pop(uid, None)

            await query.message.edit_text(
                "❌ <b>Add Channel / Group Cancelled</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=kb([
                    [
                        InlineKeyboardButton(
                            "🔙 Settings",
                            callback_data="acs_home",
                        )
                    ]
                ]),
            )
            return await query.answer("Cancelled")

        # Confirm and save the supplied ID
        if data == "acs_confirm_add":
            cid = PENDING_CHAT_ID.get(uid)

            if not isinstance(cid, int):
                return await query.answer(
                    "আগে Chat ID পাঠান।",
                    show_alert=True,
                )

            # Validate chat access and permissions
            chat = await client.get_chat(cid)

            if chat.type not in (
                enums.ChatType.CHANNEL,
                enums.ChatType.GROUP,
                enums.ChatType.SUPERGROUP,
            ):
                return await query.answer(
                    "এটি Channel / Group ID নয়।",
                    show_alert=True,
                )

            me = await client.get_me()
            member = await client.get_chat_member(chat.id, me.id)

            if not is_bot_admin(member.status):
                return await query.answer(
                    "বটকে এই Channel / Group-এ Admin করুন।",
                    show_alert=True,
                )

            # Save only after Added is pressed
            await COL.update_one(
                {"_id": int(chat.id)},
                {
                    "$set": {
                        "chat_id": int(chat.id),
                        "title": chat.title or "Group",
                        "enabled": True,
                    }
                },
                upsert=True,
            )

            PENDING_CHAT_ID.pop(uid, None)

            await query.message.edit_text(
                "✅ <b>Added Successfully!</b>\n\n"
                f"Name: <b>{escape(chat.title or 'Group')}</b>\n"
                f"ID: <code>{chat.id}</code>\n"
                "Cleaner: 🟢 ON",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=kb([
                    [
                        InlineKeyboardButton(
                            "📋 My Channels",
                            callback_data="acs_saved_0",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "➕ Add Another",
                            callback_data="acs_add_id",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Settings",
                            callback_data="acs_home",
                        )
                    ],
                ]),
            )
            return await query.answer("Added!")

        # No-op
        if data == "acs_noop":
            return await query.answer(
                "কোনো সেভ করা চ্যাট নেই।",
                show_alert=True,
            )

        # Saved chat list
        if data.startswith("acs_saved_"):
            page = int(data.rsplit("_", 1)[1])
            markup, total = await build_saved_list(page)

            await query.message.edit_text(
                "📋 <b>My Channels / Groups</b>\n"
                f"Total: <b>{total}</b>\n\n"
                "চ্যাটের নাম অথবা ID-তে চাপুন।",
                reply_markup=markup,
                parse_mode=enums.ParseMode.HTML,
            )
            return await query.answer()

        # Chat details, toggle, delete
        if data.startswith((
            "acs_detail_",
            "acs_toggle_",
            "acs_delete_",
        )):
            action, raw_id = data[4:].rsplit("_", 1)
            cid = int(raw_id)

            doc = await COL.find_one({"_id": cid})

            if not doc:
                return await query.answer(
                    "চ্যানেল পাওয়া যায়নি।",
                    show_alert=True,
                )

            # Delete
            if action == "delete":
                await COL.delete_one({"_id": cid})

                markup, total = await build_saved_list(0)

                await query.message.edit_text(
                    "🗑 <b>Chat Deleted</b>\n\n"
                    "📋 <b>My Channels / Groups</b>\n"
                    f"Total: <b>{total}</b>",
                    reply_markup=markup,
                    parse_mode=enums.ParseMode.HTML,
                )
                return await query.answer("Deleted!")

            # Toggle ON/OFF
            if action == "toggle":
                doc["enabled"] = not bool(
                    doc.get("enabled", False)
                )

                await COL.update_one(
                    {"_id": cid},
                    {"$set": {"enabled": doc["enabled"]}},
                )

                await query.answer(
                    "Cleaner ON"
                    if doc["enabled"]
                    else "Cleaner OFF"
                )

            # Refresh document after toggle
            doc = await COL.find_one({"_id": cid})

            if not doc:
                return await query.answer(
                    "চ্যানেল পাওয়া যায়নি।",
                    show_alert=True,
                )

            title = escape(doc.get("title", "Chat"))
            enabled = bool(doc.get("enabled", False))

            await query.message.edit_text(
                f"📢 <b>{title}</b>\n"
                f"ID: <code>{cid}</code>\n"
                "Cleaner: "
                f"<b>{'🟢 ON' if enabled else '🔴 OFF'}</b>",
                reply_markup=detail_kb(cid, enabled),
                parse_mode=enums.ParseMode.HTML,
            )

            return

    except RPCError as exc:
        LOG.warning("Channel settings RPC error: %s", exc)

        try:
            await query.answer(
                "চ্যাটের অ্যাক্সেস ও Admin permission যাচাই করুন।",
                show_alert=True,
            )
        except RPCError:
            pass

    except Exception:
        LOG.exception("Channel settings error")

        try:
            await query.answer(
                "Error occurred. লগ চেক করুন।",
                show_alert=True,
            )
        except RPCError:
            pass


# --------------------------------------------------
# Main Auto Cleaner helper
# --------------------------------------------------

async def is_cleaner_channel_enabled(chat_id):
    doc = await COL.find_one({
        "_id": int(chat_id),
        "enabled": True,
    })
    return bool(doc)
