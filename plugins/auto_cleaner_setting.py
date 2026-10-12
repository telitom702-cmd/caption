import logging
from html import escape

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError

from info import ADMINS
from plugins.database.database import db

LOG = logging.getLogger(__name__)
COL = db.db["auto_cleaner_channels"]
FOUND = db.db["auto_cleaner_discovered"]
LIMIT = 8


def kb(rows):
    return InlineKeyboardMarkup(rows)


def home_kb():
    return kb([
        [InlineKeyboardButton("➕ Add Channel / Group", callback_data="acs_list_0")],
        [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="acs_home")],
        [InlineKeyboardButton("🔙 Main Cleaner", callback_data="acs_main")]
    ])


async def home_text():
    total = await COL.count_documents({})
    active = await COL.count_documents({"enabled": True})
    found = await FOUND.count_documents({})
    return (
        "📢 <b>Channel / Group Settings</b>\n\n"
        f"Detected Chats: <b>{found}</b>\n"
        f"Saved Chats: <b>{total}</b>\n"
        f"Cleaner ON: <b>{active}</b>\n\n"
        "Add Channel চাপুন এবং তালিকা থেকে নির্বাচন করুন।"
    )


# বটকে কোনো চ্যানেল/গ্রুপে যুক্ত করার আপডেট পেলে ID সংগ্রহ
@Client.on_my_chat_member()
async def remember_chat(client, update):
    try:
        chat = update.chat
        status = update.new_chat_member.status

        if chat.type not in (
            enums.ChatType.CHANNEL,
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ):
            return

        if status not in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ):
            return

        await FOUND.update_one(
            {"_id": int(chat.id)},
            {"$set": {
                "chat_id": int(chat.id),
                "title": chat.title or "Group",
                "type": str(chat.type),
                "bot_admin": True
            }},
            upsert=True
        )
        LOG.info("Detected chat: %s (%s)", chat.title, chat.id)

    except Exception:
        LOG.exception("Could not save detected chat")


async def build_list(client, page=0, saved=False):
    collection = COL if saved else FOUND
    docs = await collection.find({}).sort("title", 1).to_list(1000)
    items = docs[page * LIMIT:(page + 1) * LIMIT]
    rows = []

    for doc in items:
        cid = int(doc["_id"])
        title = escape(doc.get("title", "Chat"))

        if saved:
            status = "🟢" if doc.get("enabled") else "🔴"
            label = f"{status} {doc.get('title', 'Chat')}"
            callback = f"acs_detail_{cid}"
        else:
            exists = await COL.find_one({"_id": cid})
            label = f"{'✅' if exists else '➕'} {doc.get('title', 'Chat')}"
            callback = f"acs_select_{cid}"

        rows.append([InlineKeyboardButton(label[:60], callback_data=callback)])
        # ID আলাদা বাটনে দেখানো হবে
        rows.append([InlineKeyboardButton(
            f"🆔 {cid}", callback_data=f"acs_select_{cid}"
            if not saved else f"acs_detail_{cid}"
        )])

    if not items:
        rows.append([InlineKeyboardButton(
            "কোনো চ্যানেল/গ্রুপ পাওয়া যায়নি", callback_data="acs_noop"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ Previous",
            callback_data=f"acs_{'saved' if saved else 'list'}_{page-1}"
        ))
    if (page + 1) * LIMIT < len(docs):
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
    return kb(rows), len(docs)


def detail_kb(cid, enabled):
    return kb([
        [InlineKeyboardButton(
            "🔴 Turn OFF" if enabled else "🟢 Turn ON",
            callback_data=f"acs_toggle_{cid}"
        )],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"acs_delete_{cid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="acs_saved_0")],
        [InlineKeyboardButton("❌ Cancel", callback_data="acs_home")]
    ])


@Client.on_callback_query(filters.regex(r"^acs_"))
async def channel_settings_callback(client, query):
    if not query.from_user or query.from_user.id not in ADMINS:
        return await query.answer("Admins only!", show_alert=True)

    data = query.data

    try:
        if data == "acs_home":
            await query.message.edit_text(
                await home_text(), reply_markup=home_kb(),
                parse_mode=enums.ParseMode.HTML
            )
            return await query.answer()

        if data == "acs_main":
            from plugins.auto_cleaner import cleaner_menu, cleaner_keyboard
            await query.message.edit_text(
                await cleaner_menu(),
                reply_markup=await cleaner_keyboard(),
                parse_mode=enums.ParseMode.HTML
            )
            return await query.answer()

        if data == "acs_noop":
            return await query.answer("কোনো চ্যাট পাওয়া যায়নি।", show_alert=True)

        if data.startswith(("acs_list_", "acs_saved_")):
            saved = data.startswith("acs_saved_")
            page = int(data.rsplit("_", 1)[1])
            markup, total = await build_list(client, page, saved)
            title = "📋 My Channels" if saved else "➕ Select Channel / Group"
            await query.message.edit_text(
                f"<b>{title}</b>\nTotal: <b>{total}</b>\n\n"
                "নাম অথবা ID বাটনে চাপুন।",
                reply_markup=markup, parse_mode=enums.ParseMode.HTML
            )
            return await query.answer()

        if data.startswith("acs_select_"):
            cid = int(data.rsplit("_", 1)[1])
            found = await FOUND.find_one({"_id": cid})

            if not found:
                return await query.answer(
                    "চ্যাটের তথ্য পাওয়া যায়নি। বটকে আবার যুক্ত করুন।",
                    show_alert=True
                )

            chat = await client.get_chat(cid)
            me = await client.get_me()
            member = await client.get_chat_member(cid, me.id)

            if member.status not in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ):
                return await query.answer(
                    "বটকে চ্যানেল/গ্রুপে Admin করুন।", show_alert=True
                )

            await COL.update_one(
                {"_id": cid},
                {"$set": {
                    "chat_id": cid,
                    "title": chat.title or "Group",
                    "enabled": True
                }},
                upsert=True
            )
            await query.answer("চ্যানেল/গ্রুপ সেভ হয়েছে!")
            return await query.message.edit_text(
                f"✅ <b>Selected</b>\n\n"
                f"Name: <b>{escape(chat.title or 'Group')}</b>\n"
                f"ID: <code>{cid}</code>",
                reply_markup=kb([
                    [InlineKeyboardButton("📋 My Channels", callback_data="acs_saved_0")],
                    [InlineKeyboardButton("🔙 Settings", callback_data="acs_home")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="acs_home")]
                ]),
                parse_mode=enums.ParseMode.HTML
            )

        if data.startswith(("acs_detail_", "acs_toggle_", "acs_delete_")):
            action, raw_id = data[4:].rsplit("_", 1)
            cid = int(raw_id)
            doc = await COL.find_one({"_id": cid})

            if not doc:
                return await query.answer("চ্যানেল পাওয়া যায়নি।", show_alert=True)

            if action == "delete":
                await COL.delete_one({"_id": cid})
                await query.answer("Deleted")
                markup, total = await build_list(client, 0, True)
                return await query.message.edit_text(
                    f"📋 <b>My Channels</b>\nTotal: <b>{total}</b>",
                    reply_markup=markup, parse_mode=enums.ParseMode.HTML
                )

            if action == "toggle":
                doc["enabled"] = not bool(doc.get("enabled", False))
                await COL.update_one(
                    {"_id": cid}, {"$set": {"enabled": doc["enabled"]}}
                )
                await query.answer(
                    "Cleaner ON" if doc["enabled"] else "Cleaner OFF"
                )

            await query.message.edit_text(
                f"📢 <b>{escape(doc.get('title', 'Chat'))}</b>\n"
                f"ID: <code>{cid}</code>\n"
                f"Cleaner: <b>{'🟢 ON' if doc.get('enabled') else '🔴 OFF'}</b>",
                reply_markup=detail_kb(cid, bool(doc.get("enabled"))),
                parse_mode=enums.ParseMode.HTML
            )
            return

    except (ValueError, RPCError) as exc:
        LOG.warning("Channel settings error: %s", exc)
        await query.answer(
            "চ্যানেল/গ্রুপের অ্যাক্সেস ও Admin permission যাচাই করুন।",
            show_alert=True
        )
    except Exception:
        LOG.exception("Channel settings error")
        await query.answer("Error occurred.", show_alert=True)
