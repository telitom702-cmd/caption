import asyncio
import logging
import re
from datetime import datetime
from html import escape

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from plugins.database.database import db

LOGGER = logging.getLogger(__name__)

# Keep the same collection and settings used by the original Auto Cleaner.
COLLECTION_NAME = "auto_cleaner"
cleaner_col = db.db[COLLECTION_NAME]

CLEANER_STATE = {}
CHANNEL_STATE = {}
SCAN_TASKS = {}
SCAN_PAUSE = {}
SCAN_PROGRESS = {}

DEFAULT_SETTINGS = {
    "_id": "settings",
    "enabled": False,
    "caption_cleaner": True,
    "remove_texts": ["[CineBari.com]", "MovieBaaz.com"],
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def get_settings():
    data = await cleaner_col.find_one({"_id": "settings"})
    if data is None:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$setOnInsert": DEFAULT_SETTINGS.copy()},
            upsert=True,
        )
        data = await cleaner_col.find_one({"_id": "settings"})
    return data or DEFAULT_SETTINGS.copy()


async def update_settings(data):
    try:
        await cleaner_col.update_one(
            {"_id": "settings"},
            {"$set": data},
            upsert=True,
        )
        return True
    except Exception:
        LOGGER.exception("Failed to update Auto Cleaner settings")
        return False


async def get_remove_texts():
    return (await get_settings()).get("remove_texts", [])


async def add_remove_text(text):
    text = (text or "").strip()
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


def channel_key(chat_id):
    return f"channel:{int(chat_id)}"


async def get_channels():
    cursor = cleaner_col.find({"type": "channel"}).sort("title", 1)
    return await cursor.to_list(length=None)


async def get_channel(chat_id):
    return await cleaner_col.find_one({
        "_id": channel_key(chat_id),
        "type": "channel",
    })


async def save_channel(chat):
    await cleaner_col.update_one(
        {"_id": channel_key(chat.id)},
        {"$set": {
            "type": "channel",
            "chat_id": int(chat.id),
            "title": chat.title or str(chat.id),
            "enabled": True,
        }},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Caption cleaning
# ---------------------------------------------------------------------------

def clean_text(text, remove_texts):
    if not text:
        return ""

    result = text
    for remove_text in remove_texts:
        if remove_text:
            result = re.sub(
                re.escape(remove_text),
                "",
                result,
                flags=re.IGNORECASE,
            )

    result = re.sub(r"\[\s*\]", "", result)
    result = re.sub(r"^[\s\-_:|]+$", "", result, flags=re.MULTILINE)
    return "\n".join(
        line.strip() for line in result.splitlines() if line.strip()
    ).strip()


async def is_processed(chat_id, message_id):
    return bool(await cleaner_col.find_one({
        "type": "processed",
        "chat_id": int(chat_id),
        "message_id": int(message_id),
    }))


async def mark_processed(chat_id, message_id):
    await cleaner_col.update_one(
        {
            "type": "processed",
            "chat_id": int(chat_id),
            "message_id": int(message_id),
        },
        {"$set": {
            "type": "processed",
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "processed_at": datetime.utcnow(),
        }},
        upsert=True,
    )


async def process_caption(message):
    if not message.caption:
        return False

    settings = await get_settings()
    remove_texts = settings.get("remove_texts", [])
    if not remove_texts:
        return False

    new_caption = clean_text(message.caption, remove_texts)
    if new_caption == message.caption:
        return False

    try:
        await message.edit_caption(caption=new_caption)
        LOGGER.info(
            "Caption cleaned: chat=%s message=%s",
            message.chat.id,
            message.id,
        )
        return True
    except Exception:
        LOGGER.exception(
            "Caption edit failed: chat=%s message=%s",
            message.chat.id,
            message.id,
        )
        return False


async def process_message(message):
    settings = await get_settings()
    if not settings.get("enabled", False):
        return

    # New posts are eligible only in channels explicitly saved and enabled.
    channel = await get_channel(message.chat.id)
    if not channel or not channel.get("enabled", True):
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
        LOGGER.exception("Auto Cleaner handler error")


# ---------------------------------------------------------------------------
# Main menu and reusable UI renderers
# ---------------------------------------------------------------------------

async def cleaner_menu():
    settings = await get_settings()
    enabled = settings.get("enabled", False)
    caption_enabled = settings.get("caption_cleaner", True)
    texts = settings.get("remove_texts", [])

    return (
        "🧹 <b>Auto Cleaner</b>\n\n"
        f"Status: <b>{'🟢 ON' if enabled else '🔴 OFF'}</b>\n"
        f"Caption Cleaner: <b>{'🟢 ON' if caption_enabled else '🔴 OFF'}</b>\n"
        f"Remove Texts: <b>{len(texts)}</b>\n\n"
        "নিচের বাটন দিয়ে সেটিংস নিয়ন্ত্রণ করুন।"
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
            InlineKeyboardButton("➕ Add Channel", callback_data="oldclean_add"),
            InlineKeyboardButton("📋 Channel List", callback_data="oldclean_list"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="ac_refresh"),
            InlineKeyboardButton("❌ Close", callback_data="ac_close"),
        ],
    ])


async def edit_main_menu(message):
    await message.edit_text(
        await cleaner_menu(),
        reply_markup=await cleaner_keyboard(),
        parse_mode=enums.ParseMode.HTML,
    )


async def render_channel_list(message):
    channels = await get_channels()

    if not channels:
        await message.edit_text(
            "📋 <b>Channel List</b>\n\nকোনো চ্যানেল সেভ করা নেই।",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➕ Add Channel",
                    callback_data="oldclean_add",
                )],
                [InlineKeyboardButton(
                    "⬅️ Main Menu",
                    callback_data="ac_refresh",
                )],
            ]),
        )
        return

    lines = ["📋 <b>Channel List</b>\n"]
    buttons = []

    for channel in channels:
        chat_id = int(channel["chat_id"])
        title = escape(channel.get("title", str(chat_id)))
        enabled = channel.get("enabled", True)
        status = "🟢 ON" if enabled else "🔴 OFF"

        lines.append(
            f"📢 <b>{title}</b>\n"
            f"🆔 <code>{chat_id}</code>\n"
            f"Status: {status}"
        )
        buttons.append([
            InlineKeyboardButton(
                f"{status} — Toggle",
                callback_data=f"oldclean_toggle:{chat_id}",
            ),
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"oldclean_delete:{chat_id}",
            ),
        ])

    buttons.extend([
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="oldclean_add"),
            InlineKeyboardButton("🔄 Refresh", callback_data="oldclean_list"),
        ],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="ac_refresh")],
    ])

    await message.edit_text(
        "\n\n".join(lines),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def channel_keyboard(chat_id, enabled):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 ON" if enabled else "🔴 OFF",
                callback_data=f"oldclean_toggle:{chat_id}",
            ),
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"oldclean_delete:{chat_id}",
            ),
        ],
        [InlineKeyboardButton(
            "⬅️ Channel List",
            callback_data="oldclean_list",
        )],
    ])


# Store the control panel's message location so input can update that same
# panel instead of sending another bot message.
def remember_panel(state_dict, user_id, action, message):
    state_dict[user_id] = {
        "action": action,
        "chat_id": message.chat.id,
        "message_id": message.id,
    }


async def edit_saved_panel(client, state_dict, user_id, fallback_message=None):
    state = state_dict.get(user_id)
    if not state:
        return False

    try:
        panel = await client.get_messages(
            state["chat_id"],
            state["message_id"],
        )
        if not panel or getattr(panel, "empty", False):
            return False
        await panel.edit_text(
            await cleaner_menu(),
            reply_markup=await cleaner_keyboard(),
            parse_mode=enums.ParseMode.HTML,
        )
        return True
    except Exception:
        LOGGER.exception("Could not update saved panel")
        return False


@Client.on_message(
    filters.private & filters.command("cleaner") & filters.user(ADMINS)
)
async def cleaner_command(client, message):
    await message.reply_text(
        await cleaner_menu(),
        reply_markup=await cleaner_keyboard(),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^ac_") & filters.user(ADMINS))
async def cleaner_callback(client, query):
    user_id = query.from_user.id
    data = query.data

    if data == "ac_close":
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
        await query.answer(
            "Updated" if ok else "Could not save settings",
            show_alert=not ok,
        )

    elif data == "ac_caption":
        settings = await get_settings()
        ok = await update_settings({
            "caption_cleaner": not settings.get("caption_cleaner", True)
        })
        await query.answer(
            "Updated" if ok else "Could not save settings",
            show_alert=not ok,
        )

    elif data == "ac_add":
        remember_panel(CLEANER_STATE, user_id, "add", query.message)
        await query.message.edit_text(
            "📝 যে টেক্সট সরাতে চান সেটি পাঠান।\n\n"
            "ইনপুট দেওয়ার পর এই প্যানেল আবার মেনুতে ফিরবে।\n"
            "বাতিল করতে /cancel লিখুন।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="ac_refresh")
            ]]),
        )
        await query.answer()
        return

    elif data == "ac_delete":
        texts = await get_remove_texts()
        if not texts:
            await query.answer("Remove Texts list empty!", show_alert=True)
            return

        buttons = [
            [InlineKeyboardButton(
                f"❌ {text[:30]}",
                callback_data=f"ac_del_{i}",
            )]
            for i, text in enumerate(texts)
        ]
        buttons.extend([
            [InlineKeyboardButton("🔙 Back", callback_data="ac_refresh")],
            [InlineKeyboardButton("❌ Close", callback_data="ac_close")],
        ])
        await query.message.edit_text(
            "🗑 <b>সরানোর টেক্সট নির্বাচন করুন:</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
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
                "Deleted" if ok else "Could not delete",
                show_alert=not ok,
            )
        except (ValueError, IndexError):
            await query.answer("Invalid selection", show_alert=True)
            return

    elif data == "ac_refresh":
        # If the button was used to cancel an input flow, clear its state.
        CLEANER_STATE.pop(user_id, None)
        CHANNEL_STATE.pop(user_id, None)
        await query.answer()

    else:
        await query.answer()

    try:
        await edit_main_menu(query.message)
    except Exception:
        LOGGER.exception("Could not refresh Auto Cleaner menu")


# ---------------------------------------------------------------------------
# Input handlers: bot updates the existing panel, not a new bot message.
# ---------------------------------------------------------------------------

@Client.on_message(
    filters.private & filters.text & filters.user(ADMINS)
    & ~filters.command(["cancel", "start", "cleaner", "clean", "id", "stats"])
)
async def cleaner_text_input(client, message):
    user_id = message.from_user.id
    value = (message.text or "").strip()

    cleaner_state = CLEANER_STATE.get(user_id)
    if isinstance(cleaner_state, dict) and cleaner_state.get("action") == "add":
        if not value:
            return
        if not await add_remove_text(value):
            try:
                panel = await client.get_messages(
                    cleaner_state["chat_id"],
                    cleaner_state["message_id"],
                )
                await panel.edit_text(
                    "❌ টেক্সট সেভ করা যায়নি। আবার চেষ্টা করুন।",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="ac_refresh")
                    ]]),
                )
            except Exception:
                pass
            return

        CLEANER_STATE.pop(user_id, None)
        try:
            panel = await client.get_messages(
                cleaner_state["chat_id"],
                cleaner_state["message_id"],
            )
            await panel.edit_text(
                f"✅ টেক্সট যোগ হয়েছে: <code>{escape(value)}</code>\n\n"
                + await cleaner_menu(),
                reply_markup=await cleaner_keyboard(),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            LOGGER.exception("Could not update panel after adding text")
        return

    channel_state = CHANNEL_STATE.get(user_id)
    if isinstance(channel_state, dict) and channel_state.get("action") == "add_id":
        try:
            chat_id = int(value)
            chat = await client.get_chat(chat_id)
            if chat.type != enums.ChatType.CHANNEL:
                raise ValueError("not a channel")
        except Exception:
            try:
                panel = await client.get_messages(
                    channel_state["chat_id"],
                    channel_state["message_id"],
                )
                await panel.edit_text(
                    "❌ চ্যানেল পাওয়া যায়নি বা ID ভুল।\n"
                    "সঠিক numeric channel ID আবার পাঠান, অথবা Cancel চাপুন।",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Cancel", callback_data="ac_refresh")
                    ]]),
                )
            except Exception:
                pass
            return

        try:
            await save_channel(chat)
        except Exception:
            LOGGER.exception("Failed to save channel")
            return

        CHANNEL_STATE.pop(user_id, None)
        try:
            panel = await client.get_messages(
                channel_state["chat_id"],
                channel_state["message_id"],
            )
            await render_channel_list(panel)
        except Exception:
            LOGGER.exception("Could not render channel list after saving")
        return


@Client.on_message(
    filters.private & filters.command("cancel") & filters.user(ADMINS)
)
async def cancel_states(client, message):
    user_id = message.from_user.id
    cleaner_state = CLEANER_STATE.pop(user_id, None)
    channel_state = CHANNEL_STATE.pop(user_id, None)

    state = cleaner_state or channel_state
    if isinstance(state, dict):
        try:
            panel = await client.get_messages(state["chat_id"], state["message_id"])
            await edit_main_menu(panel)
            return
        except Exception:
            LOGGER.exception("Could not restore panel after cancel")

    # Only send a short response if there was no editable panel state.
    await message.reply_text("❎ বাতিল করা হয়েছে।")


# ---------------------------------------------------------------------------
# Channel management: all list/toggle/delete actions edit the same panel.
# ---------------------------------------------------------------------------

@Client.on_callback_query(
    filters.regex(r"^oldclean_add$") & filters.user(ADMINS)
)
async def oldclean_add(client, query):
    remember_panel(CHANNEL_STATE, query.from_user.id, "add_id", query.message)
    await query.answer()
    await query.message.edit_text(
        "➕ <b>চ্যানেল যোগ করুন</b>\n\n"
        "চ্যানেলের numeric ID পাঠান।\n"
        "উদাহরণ: <code>-1001234567890</code>\n\n"
        "বটের চ্যানেলটি দেখার অ্যাক্সেস থাকতে হবে।\n"
        "বাতিল করতে /cancel লিখুন।",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="ac_refresh")
        ]]),
    )


@Client.on_callback_query(
    filters.regex(r"^oldclean_list$") & filters.user(ADMINS)
)
async def oldclean_list(client, query):
    await query.answer()
    try:
        await render_channel_list(query.message)
    except Exception:
        LOGGER.exception("Could not render channel list")
        await query.answer("Channel List দেখানো যায়নি।", show_alert=True)


@Client.on_callback_query(
    filters.regex(r"^oldclean_toggle:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_toggle(client, query):
    chat_id = int(query.data.split(":", 1)[1])
    channel = await get_channel(chat_id)

    if not channel:
        await query.answer("চ্যানেল তালিকায় নেই।", show_alert=True)
        return

    enabled = not channel.get("enabled", True)
    try:
        await cleaner_col.update_one(
            {"_id": channel_key(chat_id), "type": "channel"},
            {"$set": {"enabled": enabled}},
        )
        await render_channel_list(query.message)
        await query.answer("চ্যানেল ON করা হয়েছে।" if enabled else "চ্যানেল OFF করা হয়েছে।")
    except Exception:
        LOGGER.exception("Could not toggle channel")
        await query.answer("স্ট্যাটাস পরিবর্তন করা যায়নি।", show_alert=True)


@Client.on_callback_query(
    filters.regex(r"^oldclean_delete:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_delete(client, query):
    chat_id = int(query.data.split(":", 1)[1])
    try:
        await cleaner_col.delete_one({
            "_id": channel_key(chat_id),
            "type": "channel",
        })
        await query.answer("তালিকা থেকে সরানো হয়েছে।")
        await render_channel_list(query.message)
    except Exception:
        LOGGER.exception("Could not delete channel record")
        await query.answer("চ্যানেল সরানো যায়নি।", show_alert=True)


# ---------------------------------------------------------------------------
# Old-post cleaner command and scan progress
# ---------------------------------------------------------------------------

@Client.on_message(
    filters.private & filters.command("clean") & filters.user(ADMINS)
)
async def oldclean_command(client, message):
    # A manual cleanup covers only channels explicitly saved and ON in the
    # cleaner's channel list. No forwarded post is needed to select them.
    settings = await get_settings()
    if not settings.get("enabled", False):
        await message.reply_text(
            "❌ মূল Auto Cleaner OFF আছে। /cleaner থেকে ON করুন।"
        )
        return

    channels = [
        channel for channel in await get_channels()
        if channel.get("enabled", True)
    ]
    if not channels:
        await message.reply_text(
            "📋 ক্লিন করার মতো কোনো সেভ করা ON চ্যানেল নেই। "
            "/cleaner থেকে চ্যানেল যোগ করে ON করুন।"
        )
        return

    started = []
    already_running = []
    for channel in channels:
        try:
            chat_id = int(channel["chat_id"])
        except (KeyError, TypeError, ValueError):
            LOGGER.warning(
                "Skipping saved cleaner channel with invalid chat_id: %r",
                channel,
            )
            continue

        existing_task = SCAN_TASKS.get(chat_id)
        if existing_task and not existing_task.done():
            already_running.append(channel.get("title", str(chat_id)))
            continue

        title = escape(channel.get("title", str(chat_id)))
        status_message = await message.reply_text(
            f"🔎 <b>{title}</b>\nপুরোনো পোস্ট স্ক্যান শুরু হচ্ছে...",
            parse_mode=enums.ParseMode.HTML,
        )
        pause_event = asyncio.Event()
        pause_event.set()
        SCAN_PAUSE[chat_id] = pause_event
        SCAN_PROGRESS[chat_id] = {
            "total": 0,
            "scanned": 0,
            "cleaned": 0,
            "failed": 0,
            "message": status_message,
            "status": "Running",
        }
        SCAN_TASKS[chat_id] = asyncio.create_task(
            scan_old_posts(client, chat_id, pause_event)
        )
        started.append(channel.get("title", str(chat_id)))

    if not started:
        if already_running:
            await message.reply_text(
                "⚠️ সেভ করা ON চ্যানেলগুলোর স্ক্যান ইতিমধ্যে চলছে।"
            )
        else:
            await message.reply_text(
                "❌ সেভ করা চ্যানেলের ID সঠিক পাওয়া যায়নি। Channel List দেখে নিন।"
            )
        return

    summary = f"✅ {len(started)}টি সেভ করা ON চ্যানেলের পুরোনো পোস্ট স্ক্যান শুরু হয়েছে।"
    if already_running:
        summary += f"\n⏭️ {len(already_running)}টি চ্যানেলের স্ক্যান আগে থেকেই চলছে।"
    await message.reply_text(summary)


async def render_scan_progress(chat_id, status="Running"):
    state = SCAN_PROGRESS.get(chat_id)
    if not state:
        return

    total = state["total"]
    scanned = state["scanned"]
    percent = int(scanned * 100 / total) if total else (100 if status == "Completed" else 0)
    filled = min(10, percent // 10)
    bar = "█" * filled + "░" * (10 - filled)
    scanned_label = f"{scanned}/{total}" if total else f"{scanned} (মোট গণনা চলছে)"

    text = (
        "🧹 <b>Old Post Cleaner</b>\n\n"
        f"📊 <code>{bar}</code> {percent}%\n"
        f"🔎 Scanned: <code>{scanned_label}</code>\n"
        f"✅ Cleaned: <code>{state['cleaned']}</code>\n"
        f"❌ Failed: <code>{state['failed']}</code>\n"
        f"⚙️ Status: <b>{escape(status)}</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸ Pause", callback_data=f"oldclean_pause:{chat_id}"),
            InlineKeyboardButton("▶️ Resume", callback_data=f"oldclean_resume:{chat_id}"),
        ],
        [InlineKeyboardButton("🔄 Progress", callback_data=f"oldclean_progress:{chat_id}")],
    ])

    try:
        await state["message"].edit_text(
            text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=keyboard,
        )
    except Exception:
        LOGGER.debug("Progress message unchanged or unavailable", exc_info=True)


async def scan_old_posts(client, chat_id, pause_event):
    state = SCAN_PROGRESS[chat_id]

    try:
        await render_scan_progress(chat_id, "Running")

        async for post in client.get_chat_history(chat_id):
            await pause_event.wait()

            settings = await get_settings()
            channel = await get_channel(chat_id)

            if not settings.get("enabled", False) or not channel or not channel.get("enabled", True):
                state["status"] = "Stopped: Cleaner/Channel OFF"
                await render_scan_progress(chat_id, "Stopped: Cleaner/Channel OFF")
                return

            try:
                # Process history items directly: fetching each ID again made
                # large backfills needlessly slow and could hit Telegram limits.
                # Older posts may be photos, videos, documents, or other media;
                # captions are the reliable eligibility check for caption edits.
                if post and post.media and post.caption:
                    settings = await get_settings()
                    if settings.get("caption_cleaner", True) and post.caption:
                        new_caption = clean_text(
                            post.caption,
                            settings.get("remove_texts", []),
                        )
                        if new_caption != post.caption:
                            await post.edit_caption(caption=new_caption)
                            state["cleaned"] += 1
            except Exception:
                state["failed"] += 1
                LOGGER.exception(
                    "Old scan failed: chat=%s message=%s",
                    chat_id,
                    getattr(post, "id", "unknown"),
                )

            state["scanned"] += 1
            if state["scanned"] % 10 == 0:
                await render_scan_progress(
                    chat_id,
                    "Paused" if not pause_event.is_set() else "Running",
                )

        state["total"] = state["scanned"]
        state["status"] = "Completed"
        await render_scan_progress(chat_id, "Completed")

    except asyncio.CancelledError:
        state["status"] = "Cancelled"
        await render_scan_progress(chat_id, "Cancelled")
        raise
    except Exception as exc:
        state["status"] = f"Failed: {type(exc).__name__}"
        LOGGER.exception("Old post scan failed for %s", chat_id)
        await render_scan_progress(chat_id, state["status"])
    finally:
        SCAN_TASKS.pop(chat_id, None)
        SCAN_PAUSE.pop(chat_id, None)


@Client.on_callback_query(
    filters.regex(r"^oldclean_pause:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_pause(client, query):
    chat_id = int(query.data.split(":", 1)[1])
    event = SCAN_PAUSE.get(chat_id)
    if not event:
        await query.answer("চলমান স্ক্যান নেই।", show_alert=True)
        return

    event.clear()
    await query.answer("স্ক্যান Pause করা হয়েছে।")
    await render_scan_progress(chat_id, "Paused")


@Client.on_callback_query(
    filters.regex(r"^oldclean_resume:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_resume(client, query):
    chat_id = int(query.data.split(":", 1)[1])
    event = SCAN_PAUSE.get(chat_id)
    if not event:
        await query.answer("চলমান স্ক্যান নেই।", show_alert=True)
        return

    event.set()
    await query.answer("স্ক্যান Resume করা হয়েছে।")
    await render_scan_progress(chat_id, "Running")


@Client.on_callback_query(
    filters.regex(r"^oldclean_progress:-?\d+$") & filters.user(ADMINS)
)
async def oldclean_progress(client, query):
    chat_id = int(query.data.split(":", 1)[1])
    await query.answer()

    event = SCAN_PAUSE.get(chat_id)
    status = "Paused" if event and not event.is_set() else "Running"
    if chat_id not in SCAN_TASKS:
        status = SCAN_PROGRESS.get(chat_id, {}).get("status", "Completed")

    await render_scan_progress(chat_id, status)
