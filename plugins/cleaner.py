
# plugins/auto_cleaner_old_posts.py
# Original Channel Post Cleaner
# Forward old posts to bot's private chat
# Includes per-post progress bar

import logging
from html import escape

from pyrogram import Client, filters, enums
from pyrogram.errors import RPCError

from info import ADMINS
from plugins.auto_cleaner import (
    is_enabled,
    get_settings,
    clean_text,
)
from plugins.auto_cleaner_setting import (
    is_cleaner_channel_enabled,
)

LOGGER = logging.getLogger(__name__)


def make_progress(current, total, width=12):
    if total <= 0:
        return "[" + "░" * width + "] 0%"

    percent = int(current * 100 / total)
    filled = int(width * current / total)

    return (
        f"[{'█' * filled}{'░' * (width - filled)}] "
        f"{percent}%"
    )


@Client.on_message(
    filters.private
    & filters.user(ADMINS)
    & filters.media,
    group=20,
)
async def clean_forwarded_original_post(client, message):
    # Only process forwarded messages with identifiable origins.
    source_chat = getattr(message, "forward_from_chat", None)
    source_message_id = getattr(
        message, "forward_from_message_id", None
    )

    if not source_chat or not source_message_id:
        return

    status = None

    try:
        status = await message.reply_text(
            "🧹 <b>Original Post Cleaner</b>\n\n"
            "🔎 মূল পোস্ট খোঁজা হচ্ছে...\n"
            f"{make_progress(0, 3)}",
            parse_mode=enums.ParseMode.HTML,
        )

        if not await is_enabled():
            await status.edit_text(
                "❌ Global Auto Cleaner OFF আছে।"
            )
            return

        if source_chat.type not in (
            enums.ChatType.CHANNEL,
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ):
            await status.edit_text(
                "❌ Original Channel / Group শনাক্ত করা যায়নি।"
            )
            return

        if not await is_cleaner_channel_enabled(source_chat.id):
            await status.edit_text(
                "❌ এই Channel / Group-এর Cleaner OFF আছে।"
            )
            return

        await status.edit_text(
            "🧹 <b>Original Post Cleaner</b>\n\n"
            f"📢 {escape(source_chat.title or 'Channel')}\n"
            f"🆔 <code>{source_chat.id}</code>\n"
            f"{make_progress(1, 3)}\n"
            "📥 মূল পোস্ট আনা হচ্ছে...",
            parse_mode=enums.ParseMode.HTML,
        )

        original = await client.get_messages(
            source_chat.id,
            source_message_id,
        )

        if not original or original.empty:
            await status.edit_text(
                "❌ Original post পাওয়া যায়নি।"
            )
            return

        if not original.caption:
            await status.edit_text(
                "ℹ️ Original post-এ caption নেই।"
            )
            return

        settings = await get_settings()

        if not settings.get("caption_cleaner", True):
            await status.edit_text(
                "❌ Caption Cleaner OFF আছে।"
            )
            return

        remove_texts = settings.get("remove_texts", [])

        if not remove_texts:
            await status.edit_text(
                "ℹ️ Remove Texts তালিকা খালি।"
            )
            return

        old_caption = original.caption
        new_caption = clean_text(old_caption, remove_texts)

        if new_caption == old_caption:
            await status.edit_text(
                "✅ পরীক্ষা সম্পন্ন!\n\n"
                "কোনো পরিবর্তন প্রয়োজন হয়নি।"
            )
            return

        await status.edit_text(
            "🧹 <b>Original Post Cleaner</b>\n\n"
            f"{make_progress(2, 3)}\n"
            "✏️ মূল পোস্ট ক্লিন হচ্ছে...",
            parse_mode=enums.ParseMode.HTML,
        )

        await original.edit_caption(caption=new_caption)

        await status.edit_text(
            "✅ <b>Original Post Cleaned!</b>\n\n"
            f"📢 {escape(source_chat.title or 'Channel')}\n"
            f"🆔 <code>{source_chat.id}</code>\n"
            f"📝 Message ID: <code>{source_message_id}</code>\n\n"
            f"{make_progress(3, 3)}\n"
            "Status: 🟢 সফল\n"
            "Target: Original Channel Post",
            parse_mode=enums.ParseMode.HTML,
        )

        LOGGER.info(
            "Original post cleaned | chat=%s | message=%s",
            source_chat.id,
            source_message_id,
        )

    except RPCError as exc:
        LOGGER.warning("Original post cleaning failed: %s", exc)

        if status:
            try:
                await status.edit_text(
                    "❌ মূল পোস্ট এডিট করা যায়নি।\n\n"
                    "বটের Admin permission, Forward-এর "
                    "মূল তথ্য এবং Telegram-এর edit সীমা পরীক্ষা করুন।"
                )
            except RPCError:
                pass

    except Exception:
        LOGGER.exception("Original post cleaner error")

        if status:
            try:
                await status.edit_text(
                    "❌ Error occurred. লগ পরীক্ষা করুন।"
                )
            except RPCError:
                pass
