# plugins/cleaner.py

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from config import ADMINS
from plugins.auto_cleaner import (
    is_enabled,
    get_settings,
    clean_text,
)
from plugins.auto_cleaner_setting import is_cleaner_channel_enabled


def get_forward_source(message):
    """Return original channel and message ID, if available."""
    source_chat = getattr(message, "forward_from_chat", None)
    source_message_id = getattr(message, "forward_from_message_id", None)

    # Fallback for libraries/versions exposing forward_origin
    if not source_chat or not source_message_id:
        origin = getattr(message, "forward_origin", None)

        if origin:
            source_chat = (
                getattr(origin, "chat", None)
                or getattr(origin, "from_chat", None)
                or source_chat
            )
            source_message_id = (
                getattr(origin, "message_id", None)
                or source_message_id
            )

    return source_chat, source_message_id


async def clean_forwarded_channel_post(client, message):
    # Only process forwarded posts that identify their original source.
    source_chat, source_message_id = get_forward_source(message)

    if not source_chat or not source_message_id:
        await message.reply_text(
            "❌ মূল চ্যানেলের পোস্ট শনাক্ত করা যায়নি।\n\n"
            "চ্যানেল থেকে সাধারণভাবে Forward করে আবার চেষ্টা করুন। "
            "মূল পোস্টের তথ্য Telegram না দিলে সেটি এভাবে ক্লিন করা সম্ভব নয়।"
        )
        return

    progress = await message.reply_text(
        "⏳ **Channel Post Cleaner**\n"
        "▰▱▱▱▱▱▱▱▱▱ 10%\n"
        "মূল পোস্ট শনাক্ত করা হয়েছে..."
    )

    try:
        # Check global cleaner status
        if not await is_enabled():
            await progress.edit_text(
                "❌ Global Auto Cleaner বন্ধ আছে। আগে এটি চালু করুন।"
            )
            return

        # Check channel-specific status
        if not await is_cleaner_channel_enabled(source_chat.id):
            await progress.edit_text(
                "❌ এই চ্যানেলের Cleaner চালু নেই।\n"
                f"চ্যানেল: {source_chat.title or source_chat.id}"
            )
            return

        settings = await get_settings()

        if not settings:
            await progress.edit_text("❌ Cleaner settings পাওয়া যায়নি।")
            return

        # Check caption cleaning setting
        if not settings.get("caption_cleaner", False):
            await progress.edit_text(
                "❌ Caption Cleaner বন্ধ আছে। Settings থেকে চালু করুন।"
            )
            return

        remove_texts = settings.get("remove_texts", [])

        if isinstance(remove_texts, str):
            remove_texts = [remove_texts]

        if not remove_texts:
            await progress.edit_text(
                "❌ Remove Text তালিকা খালি। আগে যে লেখাগুলো মুছতে চান "
                "সেগুলো সেট করুন।"
            )
            return

        await progress.edit_text(
            "⏳ **Channel Post Cleaner**\n"
            "▰▰▰▰▱▱▱▱▱▱ 40%\n"
            "মূল পোস্ট লোড করা হচ্ছে..."
        )

        original = await client.get_messages(
            source_chat.id,
            source_message_id
        )

        if not original or getattr(original, "empty", False):
            await progress.edit_text(
                "❌ মূল পোস্ট পাওয়া যায়নি। পোস্টটি মুছে ফেলা হয়ে থাকতে পারে, "
                "অথবা বটের সেটি দেখার অনুমতি নেই।"
            )
            return

        if not original.caption:
            await progress.edit_text(
                "ℹ️ মূল পোস্টে Caption নেই। তাই ক্লিন করার কিছু পাওয়া যায়নি।"
            )
            return

        await progress.edit_text(
            "⏳ **Channel Post Cleaner**\n"
            "▰▰▰▰▰▰▱▱▱▱ 60%\n"
            "Caption ক্লিন করা হচ্ছে..."
        )

        new_caption = clean_text(original.caption, remove_texts)

        if new_caption == original.caption:
            await progress.edit_text(
                "ℹ️ নির্ধারিত Remove Text মূল Caption-এ পাওয়া যায়নি।"
            )
            return

        await progress.edit_text(
            "⏳ **Channel Post Cleaner**\n"
            "▰▰▰▰▰▰▰▰▱▱ 80%\n"
            "মূল চ্যানেলের পোস্ট আপডেট করা হচ্ছে..."
        )

        await original.edit_caption(caption=new_caption)

        await progress.edit_text(
            "✅ **Caption সফলভাবে ক্লিন হয়েছে!**\n\n"
            f"📢 চ্যানেল: `{source_chat.title or source_chat.id}`\n"
            f"🆔 Message ID: `{source_message_id}`\n"
            "📊 অগ্রগতি: ▰▰▰▰▰▰▰▰▰▰ 100%\n\n"
            "মূল চ্যানেলের পোস্ট আপডেট করা হয়েছে।"
        )

    except Exception as e:
        await progress.edit_text(
            "❌ **পোস্ট ক্লিন করা যায়নি।**\n\n"
            f"কারণ: `{str(e)[:700]}`\n\n"
            "বটের Channel Admin ও Edit Messages permission পরীক্ষা করুন।"
        )


def register_cleaner_plugin(app):
    app.add_handler(
        MessageHandler(
            clean_forwarded_channel_post,
            filters.private & filters.user(ADMINS)
            & (filters.media | filters.text),
        ),
        group=20,
    )
