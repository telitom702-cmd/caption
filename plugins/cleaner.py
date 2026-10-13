# plugins/cleaner.py

import asyncio

from pyrogram import filters
from pyrogram.handlers import MessageHandler
from pyrogram.errors import FloodWait, MessageNotModified

from info import ADMINS
from plugins.auto_cleaner import (
    is_enabled,
    get_settings,
    clean_text,
)
from plugins.auto_cleaner_setting import is_cleaner_channel_enabled


def get_forward_source(message):
    chat = getattr(message, "forward_from_chat", None)
    message_id = getattr(message, "forward_from_message_id", None)

    if not chat or not message_id:
        origin = getattr(message, "forward_origin", None)
        if origin:
            chat = getattr(origin, "chat", None) or chat
            message_id = getattr(origin, "message_id", None) or message_id

    return chat, message_id


def progress_bar(percent, length=10):
    filled = int(length * percent / 100)
    return "▰" * filled + "▱" * (length - filled)


async def clean_channel_history(client, message):
    source_chat, _ = get_forward_source(message)

    if not source_chat:
        await message.reply_text(
            "❌ মূল চ্যানেল শনাক্ত করা যায়নি।\n"
            "চ্যানেল থেকে সাধারণভাবে একটি পোস্ট Forward করুন।"
        )
        return

    status = await message.reply_text("⏳ চ্যানেলের পোস্ট পরীক্ষা করা হচ্ছে...")

    try:
        if not await is_enabled():
            await status.edit_text("❌ Global Auto Cleaner বন্ধ আছে।")
            return

        if not await is_cleaner_channel_enabled(source_chat.id):
            await status.edit_text("❌ এই চ্যানেলের Cleaner চালু নেই।")
            return

        settings = await get_settings() or {}

        if not settings.get("caption_cleaner", False):
            await status.edit_text("❌ Caption Cleaner বন্ধ আছে।")
            return

        remove_texts = settings.get("remove_texts", [])
        if isinstance(remove_texts, str):
            remove_texts = [remove_texts]

        remove_texts = [x for x in remove_texts if x]

        if not remove_texts:
            await status.edit_text("❌ Remove Text তালিকা খালি।")
            return

        # Get the latest message ID visible to the bot.
        latest = await client.get_chat_history(source_chat.id, limit=1)
        latest_message = None

        async for item in latest:
            latest_message = item
            break

        if not latest_message:
            await status.edit_text("❌ চ্যানেলে কোনো পোস্ট পাওয়া যায়নি।")
            return

        max_id = latest_message.id
        checked = cleaned = skipped = failed = 0

        await status.edit_text(
            "⏳ **Channel Cleaner শুরু হয়েছে**\n"
            f"📢 {source_chat.title or source_chat.id}\n"
            f"মোট Message ID পরীক্ষা: `{max_id}`\n"
            f"Progress: {progress_bar(0)} 0%"
        )

        # Scan from the oldest ID to the newest ID.
        for message_id in range(1, max_id + 1):
            try:
                original = await client.get_messages(
                    source_chat.id, message_id
                )
                checked += 1

                if not original or getattr(original, "empty", False):
                    skipped += 1

                elif not original.caption:
                    # Text-only posts and media without captions are skipped.
                    skipped += 1

                else:
                    new_caption = clean_text(original.caption, remove_texts)

                    if new_caption == original.caption:
                        skipped += 1
                    else:
                        try:
                            await original.edit_caption(caption=new_caption)
                            cleaned += 1
                        except MessageNotModified:
                            skipped += 1
                        except Exception:
                            failed += 1

                if checked % 10 == 0 or message_id == max_id:
                    percent = int(checked * 100 / max_id)

                    try:
                        await status.edit_text(
                            "⏳ **Channel Cleaner চলছে**\n"
                            f"📢 {source_chat.title or source_chat.id}\n"
                            f"Progress: {progress_bar(percent)} {percent}%\n\n"
                            f"🔎 পরীক্ষা: `{checked}/{max_id}`\n"
                            f"✅ ক্লিন: `{cleaned}`\n"
                            f"⏭️ Skip: `{skipped}`\n"
                            f"❌ Failed: `{failed}`"
                        )
                    except MessageNotModified:
                        pass

                await asyncio.sleep(0.15)

            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                checked += 1
                failed += 1

        await status.edit_text(
            "✅ **Channel Cleaner সম্পন্ন!**\n\n"
            f"📢 {source_chat.title or source_chat.id}\n"
            f"🔎 পরীক্ষা করা: `{checked}`\n"
            f"✅ Caption ক্লিন: `{cleaned}`\n"
            f"⏭️ Skip: `{skipped}`\n"
            f"❌ Failed: `{failed}`"
        )

    except Exception as e:
        await status.edit_text(
            f"❌ Cleaner error:\n`{str(e)[:500]}`"
        )


def register_cleaner_plugin(app):
    app.add_handler(
        MessageHandler(
            clean_channel_history,
            filters.private & filters.user(ADMINS) & filters.forwarded,
        ),
        group=20,
    )
