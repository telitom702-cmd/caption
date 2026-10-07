import asyncio
import logging
import os
import time

from aiohttp import web
from pyrogram import Client, idle

from info import API_ID, API_HASH, BOT_TOKEN, SESSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

LOGGER = logging.getLogger(__name__)

app = Client(
    SESSION, # হার্ডকোড না করে info.py থেকে নেওয়া হয়েছে
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins={"root": "plugins"},
    workdir="."
)

botStartTime = time.time()


async def create_web_app():
    """Render health-check web server."""
    web_app = web.Application()

    async def health_check(request):
        return web.Response(
            text="DreamxBotz is running!",
            content_type="text/plain"
        )

    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/health", health_check)

    return web_app


async def start_web_server():
    port = int(os.environ.get("PORT", "8080"))

    web_app = await create_web_app()

    runner = web.AppRunner(web_app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=port
    )

    await site.start()

    LOGGER.info(
        "Web Server started on 0.0.0.0:%s",
        port
    )

    return runner


async def start_bot():
    LOGGER.info("Initializing DreamxBotz...")

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing!"
        )

    # তারপর bot start
    await app.start()

    bot_info = await app.get_me()

    LOGGER.info(
        "Bot started: %s (@%s)",
        bot_info.first_name,
        bot_info.username
    )

    # Render web server
    runner = await start_web_server()

    LOGGER.info(
        "Bot is now running and listening for messages..."
    )

    try:
        await idle()

    finally:
        LOGGER.info("Stopping bot...")

        try:
            await runner.cleanup()
        except Exception:
            LOGGER.exception("Web server cleanup failed")

        try:
            await app.stop()
        except Exception:
            LOGGER.exception("Bot stop failed")


if __name__ == "__main__":
    asyncio.run(start_bot())
