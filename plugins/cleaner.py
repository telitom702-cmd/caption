
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError

from info import ADMINS
from plugins.database.database import db
from plugins.auto_cleaner import get_remove_texts, clean_text

LOGGER = logging.getLogger(__name__)
cleaner_col = db.db["auto_cleaner"]
CLEAN_STATE = {}


async def get_channels():
    return await cleaner_col.find(
        {"type": "cleaner_channel"}
    ).to_list(length=500)


async def add_channel(chat_id, title, username=None):
    await cleaner_col.update_one(
        {"type": "cleaner_channel", "chat_id": int(chat_id)},
        {"$set": {
            "type": "cleaner_channel",
            "chat_id": int(chat_id),
            "title": title,
            "username": username,
            "enabled": True,
        }},
        upsert=True,
    )


def channels_keyboard(channels):
    rows = []

    for channel in channels:
        chat_id = channel["chat_id"]
        enabled = channel.get("enabled", True)
        title = channel.get("title", str(chat_id))

        rows.append([
            InlineKeyboardButton(
                f"{'🟢' if enabled else '🔴'} {title[:22]}",
                callback_data=f"cc_toggle_{chat_id}",
            ),
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"cc_delete_{chat_id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton("🔙 Back", callback_data="cc_back"),
        InlineKeyboardButton("❌ Close", callback_data="cc_close"),
    ])
    return InlineKeyboardMarkup(rows)


async def show_channel_list(query):
    channels = await get_channels()

    if not channels:
        await query.message.edit_text(
            "📋 কোনো চ্যানেল যোগ করা নেই।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="cc_back"),
                InlineKeyboardButton("❌ Close", callback_data="cc_close"),
            ]]),
        )
        return

    await query.message.edit_text(
        "📋 <b>Channel List</b>\n\n"
        "🟢 = ON | 🔴 = OFF\n"
        "চ্যানেলের নামের বাটনে চাপলে ON/OFF হবে।",
        reply_markup=channels_keyboard(channels),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^cc_"))
async def channel_callback(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("Admins only!", show_alert=True)
        return

    data = query.data
    user_id = query.from_user.id

    if data == "cc_close":
        CLEAN_STATE.pop(user_id, None)
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_reply_markup(reply_markup=None)
        return

    if data == "cc_back":
        CLEAN_STATE.pop(user_id, None)
        from plugins.auto_cleaner import cleaner_menu, cleaner_keyboard

        await query.answer()
        await query.message.edit_text(
            await cleaner_menu(),
            reply_markup=await cleaner_keyboard(),
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if data == "cc_add":
        CLEAN_STATE[user_id] = "add_channel"
        await query.answer()
        await query.message.edit_text(
            "➕ চ্যানেল থেকে একটি পোস্ট ফরওয়ার্ড করো।\n\n"
            "পোস্টের উৎস দৃশ্যমান থাকতে হবে।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
            ]]),
        )
        return

    if data == "cc_list":
        await query.answer()
        await show_channel_list(query)
        return

    if data == "cc_clean":
        CLEAN_STATE[user_id] = "clean_post"
        await query.answer()
        await query.message.edit_text(
            "🧹 যে চ্যানেলের পোস্ট ক্লিন করতে চাও, "
            "সেই চ্যানেল থেকে একটি পোস্ট ফরওয়ার্ড করো।\n\n"
            "এই Bot Client পদ্ধতিতে পুরো পুরোনো ইতিহাস স্ক্যান করা যায় না।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
            ]]),
        )
        return

    if data.startswith("cc_toggle_"):
        try:
            chat_id = int(data.rsplit("_", 1)[1])
        except ValueError:
            await query.answer("Invalid channel!", show_alert=True)
            return

        channel = await cleaner_col.find_one({
            "type": "cleaner_channel",
            "chat_id": chat_id,
        })
        if not channel:
            await query.answer("Channel not found!", show_alert=True)
            return

        new_state = not channel.get("enabled", True)
        await cleaner_col.update_one(
            {"type": "cleaner_channel", "chat_id": chat_id},
            {"$set": {"enabled": new_state}},
        )
        await query.answer("Channel ON" if new_state else "Channel OFF")
        await show_channel_list(query)
        return

    if data.startswith("cc_delete_"):
        try:
            chat_id = int(data.rsplit("_", 1)[1])
        except ValueError:
            await query.answer("Invalid channel!", show_alert=True)
            return

        await cleaner_col.delete_one({
            "type": "cleaner_channel",
            "chat_id": chat_id,
        })
        await query.answer("Channel deleted!")
        await show_channel_list(query)


@Client.on_message(filters.private & filters.command("clean"))
async def clean_command(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        await message.reply_text("You are not authorized.")
        return

    CLEAN_STATE[message.from_user.id] = "clean_post"
    await message.reply_text(
        "🧹 যে চ্যানেলের পোস্ট ক্লিন করতে চাও, "
        "সেই চ্যানেল থেকে একটি পোস্ট ফরওয়ার্ড করো।\n\n"
        "নোট: বট দিয়ে পুরো পুরোনো চ্যানেল হিস্ট্রি স্ক্যান করা যায় না।",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="cc_back")
        ]]),
    )


def get_forward_source(message):
    chat = getattr(message, "forward_from_chat", None)
    message_id = getattr(message, "forward_from_message_id", None)

    # কিছু Pyrogram সংস্করণে forward origin অবজেক্ট পাওয়া যায়।
    origin = getattr(message, "forward_origin", None)
    if not chat and origin:
        chat = getattr(origin, "chat", None)
        message_id = message_id or getattr(origin, "message_id", None)

    return chat, message_id


@Client.on_message(filters.private & filters.forwarded)
async def forwarded_channel_post(client, message):
    if not message.from_user or message.from_user.id not in ADMINS:
        return

    user_id = message.from_user.id
    state = CLEAN_STATE.get(user_id)

    if state not in ("add_channel", "clean_post"):
        return

    source_chat, source_message_id = get_forward_source(message)

    if not source_chat or not source_message_id:
        await message.reply_text(
            "❌ সোর্স চ্যানেল বা পোস্টের ID পাওয়া যায়নি। "
            "চ্যানেল থেকে সরাসরি ফরওয়ার্ড করো; hidden forward কাজ করবে না।"
        )
        return

    if state == "add_channel":
        try:
            await add_channel(
                source_chat.id,
                getattr(source_chat, "title", None) or str(source_chat.id),
                getattr(source_chat, "username", None),
            )
            CLEAN_STATE.pop(user_id, None)
            await message.reply_text("✅ Channel added successfully!")
        except Exception:
            LOGGER.exception("Failed to add channel")
            await message.reply_text("❌ চ্যানেল সংরক্ষণ করা যায়নি।")
        return

    channels = await get_channels()
    channel = next(
        (
            item for item in channels
            if item["chat_id"] == source_chat.id
            and item.get("enabled", True)
        ),
        None,
    )

    if not channel:
        await message.reply_text(
            "❌ এই চ্যানেল তালিকায় নেই অথবা OFF করা আছে।"
        )
        CLEAN_STATE.pop(user_id, None)
        return

    remove_texts = await get_remove_texts()

    if message.caption is not None:
        original = message.caption
        cleaned = clean_text(original, remove_texts)
        kind = "caption"
    elif message.text is not None:
        original = message.text
        cleaned = clean_text(original, remove_texts)
        kind = "text"
    else:
        await message.reply_text(
            "❌ এই পোস্টে সম্পাদনাযোগ্য টেক্সট বা ক্যাপশন নেই।"
        )
        CLEAN_STATE.pop(user_id, None)
        return

    if cleaned == original:
        CLEAN_STATE.pop(user_id, None)
        await message.reply_text("ℹ️ পোস্টে পরিবর্তন করার মতো টেক্সট নেই।")
        return

    progress = await message.reply_text(
        "⏳ Processing: [░░░░░░░░░░] 0%"
    )

    try:
        if kind == "caption":
            await client.edit_message_caption(
                chat_id=source_chat.id,
                message_id=source_message_id,
                caption=cleaned,
            )
        else:
            await client.edit_message_text(
                chat_id=source_chat.id,
                message_id=source_message_id,
                text=cleaned,
            )

        await progress.edit_text(
            "✅ Processing complete: [██████████] 100%\n"
            "পরীক্ষা করা হয়েছে: 1\n"
            "ক্লিন হয়েছে: 1\n"
            "ব্যর্থ: 0"
        )
    except RPCError:
        LOGGER.exception("Unable to edit source channel post")
        await progress.edit_text(
            "❌ মূল পোস্ট ক্লিন করা যায়নি।\n"
            "বটের channel permission এবং Telegram API access পরীক্ষা করো।"
        )
    except Exception:
        LOGGER.exception("Unexpected cleaning error")
        await progress.edit_text("❌ অপ্রত্যাশিত ত্রুটি হয়েছে।")
    finally:
        CLEAN_STATE.pop(user_id, None)
