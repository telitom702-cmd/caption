from pyrogram import Client, filters
from pyrogram.enums import ParseMode

@Client.on_message(
    filters.private & filters.command("start")
)
async def start_command(client, message):
    await message.reply_text(
        "🤖 <b>DramaZ.BotZ is Running!</b>\n\n"
        "✅ Bot is online and ready.\n\n"
        "<b>Admin commands</b>\n"
        "/copy — copy controls\n"
        "/copysetting — set Source/Target by numeric channel ID\n"
        "/sourcedupe — source duplicate protection\n"
        "/cleaner — caption cleaner",
        parse_mode=ParseMode.HTML
    )
