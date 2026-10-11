
# plugins/auto_cleaner_setting.py
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


async def is_cleaner_channel_enabled(chat_id):
    doc = await COL.find_one({"_id": int(chat_id)})
    return bool(doc and doc.get("enabled", False))


def channel_home_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Channel ID", callback_data="acs_list_0")],
        [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="acs_home")],
        [InlineKeyboardButton("🔙 Main Cleaner", callback_data="acs_main")]
    ])


async def channel_home_text():
    total = await COL.count_documents({})
    active = await COL.count_documents({"enabled": True})
    return (
        "📢 <b>Channel Settings</b>\n\n"
        f"Total Channels: <b>{total}</b>\n"
        f"Cleaner ON: <b>{active}</b>\n\n"
        "Add Channel চাপুন এবং তালিকা থেকে নির্বাচন করুন।"
    )


async def discover_channels(client):
    """শুধু বটের dialogs-এ পাওয়া চ্যানেলগুলো পরীক্ষা করবে।"""
    found = []
    me = await client.get_me()

    async for dialog in client.get_dialogs():
        chat = dialog.chat
        if chat.type != enums.ChatType.CHANNEL:
            continue
        try:
            member = await client.get_chat_member(chat.id, me.id)
            if member.status in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ):
                found.append({"id": int(chat.id), "title": chat.title or "Channel"})
        except RPCError:
            continue
    return found


async def build_channel_list(client, page=0, saved=False):
    if saved:
        docs = await COL.find({}).sort("title", 1).to_list(length=1000)
        items = [
            {"id": int(d["_id"]), "title": d.get("title", "Channel"),
             "enabled": d.get("enabled", False)}
            for d in docs
        ]
    else:
        items = await discover_channels(client)

    start = max(0, page) * LIMIT
    current = items[start:start + LIMIT]
    rows = []

    for item in current:
        cid = item["id"]
        if saved:
            status = "🟢" if item["enabled"] else "🔴"
            rows.append([InlineKeyboardButton(
                f"{status} {item['title']}"[:60],
                callback_data=f"acs_detail_{cid}"
            )])
        else:
            exists = await COL.find_one({"_id": cid})
            prefix = "✅ Added: " if exists else "➕ "
            rows.append([InlineKeyboardButton(
                f"{prefix}{item['title']}"[:60],
                callback_data=f"acs_select_{cid}"
            )])

    if not current:
        rows.append([InlineKeyboardButton(
            "কোনো চ্যানেল পাওয়া যায়নি", callback_data="acs_noop"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ Previous",
            callback_data=f"acs_{'saved' if saved else 'list'}_{page-1}"
        ))
    if start + LIMIT < len(items):
        nav.append(InlineKeyboardButton(
            "Next ➡️",
            callback_data=f"acs_{'saved' if saved else 'list'}_{page+1}"
        ))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("🔙 Back", callback_data="acs_home"),
        InlineKeyboardButton("❌ Cancel", callback_data="acs_home")
    ])
    return InlineKeyboardMarkup(rows), len(items)


def detail_keyboard(cid, enabled):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔴 Turn OFF" if enabled else "🟢 Turn ON",
            callback_data=f"acs_toggle_{cid}"
        )],
        [InlineKeyboardButton("🗑 Delete Channel", callback_data=f"acs_delete_{cid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="acs_saved_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="acs_home")]
    ])


@Client.on_callback_query(filters.regex(r"^acs_"))
async def channel_settings_callback(client, query):
    if not query.from_user or query.from_user.id not in ADMINS:
        return await query.answer("Admins only!", show_alert=True)

    data = query.data

    try:
        if data == "acs_main":
            # auto_cleaner.py-কে আপনার মূল Cleaner ফাইলের নাম দিয়ে বদলান।
            from plugins.auto_cleaner import cleaner_menu, cleaner_keyboard

            await query.message.edit_text(
                await cleaner_menu(),
                reply_markup=await cleaner_keyboard(),
                parse_mode=enums.ParseMode.HTML
            )
            return await query.answer()

        if data == "acs_home":
            await query.message.edit_text(
                await channel_home_text(),
                reply_markup=channel_home_kb(),
                parse_mode=enums.ParseMode.HTML
            )
            return await query.answer()

        if data == "acs_noop":
            return await query.answer("কোনো চ্যানেল পাওয়া যায়নি।", show_alert=True)

        if data.startswith(("acs_list_", "acs_saved_")):
            saved = data.startswith("acs_saved_")
            page = int(data.rsplit("_", 1)[1])
            kb, total = await build_channel_list(client, page, saved)
            title = "📋 My Channels" if saved else "➕ Select Channel"
            await query.message.edit_text(
                f"<b>{title}</b>\n\nTotal: <b>{total}</b>",
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML
            )
            return await query.answer()

        if data.startswith("acs_select_"):
            cid = int(data.rsplit("_", 1)[1])
            chat = await client.get_chat(cid)
            me = await client.get_me()
            member = await client.get_chat_member(cid, me.id)

            if member.status not in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ):
                return await query.answer(
                    "বটকে আগে চ্যানেলে Admin করুন।", show_alert=True
                )

            await COL.update_one(
                {"_id": cid},
                {"$setOnInsert": {
                    "chat_id": cid,
                    "title": chat.title or "Channel",
                    "enabled": True
                }},
                upsert=True
            )
            await query.answer("Channel added / already exists.")
            return await query.message.edit_text(
                f"✅ <b>Channel Selected</b>\n\n"
                f"Name: <b>{escape(chat.title or 'Channel')}</b>\n"
                f"ID: <code>{cid}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
                    [InlineKeyboardButton("🔙 Channel Settings", callback_data="acs_home")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="acs_main")]
                ]),
                parse_mode=enums.ParseMode.HTML
            )

        if data.startswith(("acs_detail_", "acs_toggle_", "acs_delete_")):
            action, raw_id = data[4:].rsplit("_", 1)
            cid = int(raw_id)
            doc = await COL.find_one({"_id": cid})

            if not doc:
                return await query.answer("Channel পাওয়া যায়নি।", show_alert=True)

            if action == "delete":
                await COL.delete_one({"_id": cid})
                await query.answer("Channel deleted.")
                kb, total = await build_channel_list(client, 0, True)
                return await query.message.edit_text(
                    f"📋 <b>My Channels</b>\nTotal: <b>{total}</b>",
                    reply_markup=kb,
                    parse_mode=enums.ParseMode.HTML
                )

            if action == "toggle":
                enabled = not bool(doc.get("enabled", False))
                await COL.update_one({"_id": cid}, {"$set": {"enabled": enabled}})
                doc["enabled"] = enabled
                await query.answer("Cleaner ON" if enabled else "Cleaner OFF")

            enabled = bool(doc.get("enabled", False))
            await query.message.edit_text(
                f"📢 <b>{escape(doc.get('title', 'Channel'))}</b>\n"
                f"ID: <code>{cid}</code>\n"
                f"Cleaner: <b>{'🟢 ON' if enabled else '🔴 OFF'}</b>",
                reply_markup=detail_keyboard(cid, enabled),
                parse_mode=enums.ParseMode.HTML
            )
            return

    except (ValueError, RPCError) as exc:
        LOG.warning("Channel settings error: %s", exc)
        await query.answer(
            "চ্যানেল অ্যাক্সেস বা Admin permission যাচাই করুন।",
            show_alert=True
        )
    except Exception:
        LOG.exception("Channel settings error")
        await query.answer("Error occurred.", show_alert=True)
