
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
        [InlineKeyboardButton("➕ Add Channel", callback_data="acs_list_0")],
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
        "Add Channel চাপুন, channel বাছুন; ID দেখে Confirm করলে তবেই যোগ হবে।"
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
                callback_data=f"acs_select_{cid}_{page}"
            )])

    if not current:
        if saved:
            rows.append([InlineKeyboardButton(
                "কোনো saved channel নেই", callback_data="acs_noop"
            )])
        else:
            rows.append([InlineKeyboardButton(
                "🔄 Retry channel search", callback_data="acs_list_0"
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

    callback_answered = False

    async def answer(text=None, show_alert=False):
        nonlocal callback_answered
        await query.answer(text, show_alert=show_alert)
        callback_answered = True

    try:
        if data == "acs_main":
            # auto_cleaner.py-কে আপনার মূল Cleaner ফাইলের নাম দিয়ে বদলান।
            from plugins.auto_cleaner import cleaner_menu, cleaner_keyboard

            await query.message.edit_text(
                await cleaner_menu(),
                reply_markup=await cleaner_keyboard(),
                parse_mode=enums.ParseMode.HTML
            )
            return await answer()

        if data == "acs_home":
            await query.message.edit_text(
                await channel_home_text(),
                reply_markup=channel_home_kb(),
                parse_mode=enums.ParseMode.HTML
            )
            return await answer()

        if data == "acs_noop":
            return await answer("কোনো চ্যানেল পাওয়া যায়নি।", show_alert=True)

        if data.startswith(("acs_list_", "acs_saved_")):
            saved = data.startswith("acs_saved_")
            page = int(data.rsplit("_", 1)[1])
            await answer("Saved channel তালিকা লোড হচ্ছে..." if saved else "চ্যানেল খুঁজছি...")
            kb, total = await build_channel_list(client, page, saved)
            if not saved and total == 0:
                text = (
                    "➕ <b>Add Channel</b>\n\n"
                    "কোনো channel পাওয়া যায়নি। Bot-কে target channel-এ Admin হিসেবে যোগ করে "
                    "আবার Retry করুন। Channel শুধু Confirm চাপার পরই save হবে।"
                )
            else:
                title = "📋 My Channels" if saved else "➕ Select Channel"
                text = f"<b>{title}</b>\n\nTotal: <b>{total}</b>"
                if not saved:
                    text += "\n\nএকটি channel বাছুন। ID দেখে Confirm না করা পর্যন্ত এটি যোগ হবে না।"
            await query.message.edit_text(
                text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML
            )
            return

        if data.startswith("acs_select_"):
            payload = data[len("acs_select_"):]
            parts = payload.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                raw_id, page = parts[0], int(parts[1])
            else:
                raw_id, page = payload, 0
            cid = int(raw_id)
            await answer("Channel যাচাই করছি...")
            chat = await client.get_chat(cid)
            if chat.type != enums.ChatType.CHANNEL:
                return await query.message.edit_text(
                    "❌ এটি channel নয়। আবার channel তালিকা থেকে বাছুন।",
                    reply_markup=channel_home_kb()
                )
            me = await client.get_me()
            member = await client.get_chat_member(cid, me.id)
            if member.status not in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ):
                return await query.message.edit_text(
                    "❌ Bot-কে আগে channel-এ Admin করুন, তারপর আবার বাছুন।",
                    reply_markup=channel_home_kb()
                )

            existing = await COL.find_one({"_id": cid})
            if existing:
                return await query.message.edit_text(
                    "✅ <b>Channel আগে থেকেই যোগ করা আছে</b>\n\n"
                    f"Name: <b>{escape(chat.title or 'Channel')}</b>\n"
                    f"ID: <code>{cid}</code>\n"
                    f"Cleaner: <b>{'🟢 ON' if existing.get('enabled', False) else '🔴 OFF'}</b>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
                        [InlineKeyboardButton("🔄 Back to channel list", callback_data=f"acs_list_{page}")],
                        [InlineKeyboardButton("🔙 Channel Settings", callback_data="acs_home")]
                    ]),
                    parse_mode=enums.ParseMode.HTML
                )

            return await query.message.edit_text(
                "🔎 <b>Confirm Channel</b>\n\n"
                f"Name: <b>{escape(chat.title or 'Channel')}</b>\n"
                f"ID: <code>{cid}</code>\n\n"
                "এই channel-এ Auto Cleaner চালু করতে Confirm চাপুন। Cancel করলে কিছু save হবে না।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirm Add", callback_data=f"acs_confirm_{cid}")],
                    [InlineKeyboardButton("❌ Cancel", callback_data=f"acs_canceladd_{page}")]
                ]),
                parse_mode=enums.ParseMode.HTML
            )

        if data.startswith("acs_confirm_"):
            cid = int(data[len("acs_confirm_"):])
            await answer("Channel save করছি...")
            chat = await client.get_chat(cid)
            if chat.type != enums.ChatType.CHANNEL:
                return await query.message.edit_text(
                    "❌ এটি আর channel হিসেবে পাওয়া যাচ্ছে না।", reply_markup=channel_home_kb()
                )
            me = await client.get_me()
            member = await client.get_chat_member(cid, me.id)
            if member.status not in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ):
                return await query.message.edit_text(
                    "❌ Bot channel-এ Admin নেই। Channel যোগ করা হয়নি।",
                    reply_markup=channel_home_kb()
                )

            existing = await COL.find_one({"_id": cid})
            if existing:
                await query.message.edit_text(
                    "✅ <b>Channel আগে থেকেই যোগ করা আছে</b>\n\n"
                    f"Name: <b>{escape(chat.title or 'Channel')}</b>\n"
                    f"ID: <code>{cid}</code>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
                        [InlineKeyboardButton("🔙 Channel Settings", callback_data="acs_home")]
                    ]),
                    parse_mode=enums.ParseMode.HTML
                )
                return

            await COL.update_one(
                {"_id": cid},
                {"$setOnInsert": {
                    "chat_id": cid,
                    "title": chat.title or "Channel",
                    "enabled": True
                }},
                upsert=True
            )
            await query.message.edit_text(
                "✅ <b>Channel Added</b>\n\n"
                f"Name: <b>{escape(chat.title or 'Channel')}</b>\n"
                f"ID: <code>{cid}</code>\n"
                "Cleaner: <b>🟢 ON</b>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
                    [InlineKeyboardButton("➕ Add another", callback_data="acs_list_0")],
                    [InlineKeyboardButton("🔙 Channel Settings", callback_data="acs_home")]
                ]),
                parse_mode=enums.ParseMode.HTML
            )
            return

        if data.startswith("acs_canceladd_"):
            page = int(data.rsplit("_", 1)[1])
            await answer("Cancel — channel save করা হয়নি।")
            kb, total = await build_channel_list(client, page, False)
            text = (
                "➕ <b>Select Channel</b>\n\n"
                f"Total: <b>{total}</b>\n"
                "একটি channel বাছুন; Confirm না করলে সেটি যোগ হবে না।"
            )
            if total == 0:
                text += "\n\nBot-কে target channel-এ Admin করে Retry করুন।"
            await query.message.edit_text(
                text,
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML
            )
            return

        if data.startswith(("acs_detail_", "acs_toggle_", "acs_delete_")):
            action, raw_id = data[4:].rsplit("_", 1)
            cid = int(raw_id)
            doc = await COL.find_one({"_id": cid})

            if not doc:
                return await answer("Channel পাওয়া যায়নি।", show_alert=True)

            if action == "delete":
                await COL.delete_one({"_id": cid})
                await answer("Channel deleted.")
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
                await answer("Cleaner ON" if enabled else "Cleaner OFF")

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
        if callback_answered:
            try:
                await query.message.edit_text(
                    "❌ Channel access/Admin permission যাচাই করুন, তারপর আবার চেষ্টা করুন।",
                    reply_markup=channel_home_kb()
                )
            except Exception:
                LOG.exception("Could not display channel settings error")
        else:
            await answer(
                "চ্যানেল অ্যাক্সেস বা Admin permission যাচাই করুন।",
                show_alert=True
            )
    except Exception:
        LOG.exception("Channel settings error")
        if callback_answered:
            try:
                await query.message.edit_text(
                    "❌ Error occurred. আবার চেষ্টা করুন।",
                    reply_markup=channel_home_kb()
                )
            except Exception:
                LOG.exception("Could not display channel settings error")
        else:
            await answer("Error occurred.", show_alert=True)
