from pyrogram import Client, filters


@Client.on_message(
    filters.private & filters.command("start")
)
async def start_command(client, message):
    await message.reply_text(
        "🤖 <b>DreamxBotz is Running!</b>\n\n"
        "✅ Bot is online and working.\n"
        "🚀 Ready to receive your commands.",
        parse_mode="html"
    )
