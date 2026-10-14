import asyncio
import importlib.util
import logging
import os
import sys
from importlib.machinery import SourceFileLoader

from aiohttp import web
from pyrogram import Client, idle

from info import API_ID, API_HASH, BOT_TOKEN, DATABASE_URI, SESSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

LOGGER = logging.getLogger(__name__)
app = None


def load_existing_cleaner_plugin():
    """Load the cleaner from its current extensionless file path."""
    plugin_path = os.path.join(os.path.dirname(__file__), "plugins", "auto_cleaner")
    if not os.path.isfile(plugin_path):
        raise FileNotFoundError(f"Cleaner plugin file not found: {plugin_path}")

    module_name = "plugins.auto_cleaner"
    if module_name in sys.modules:
        return

    loader = SourceFileLoader(module_name, plugin_path)
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Could not load cleaner plugin from {plugin_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise


async def create_web_app():
    """Create the Render health-check web application."""
    web_app = web.Application()

    async def health_check(request):
        return web.Response(text="DreamxBotz is running!", content_type="text/plain")

    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/health", health_check)
    return web_app


async def start_web_server():
    port = int(os.environ.get("PORT", "8080"))
    web_app = await create_web_app()
    runner = web.AppRunner(web_app)
    try:
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
    except Exception:
        await runner.cleanup()
        raise

    LOGGER.info("Web Server started on 0.0.0.0:%s", port)
    return runner


async def start_bot():
    global app
    LOGGER.info("Initializing DreamxBotz...")

    missing = []
    if API_ID <= 0:
        missing.append("API_ID")
    if not API_HASH:
        missing.append("API_HASH")
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not DATABASE_URI:
        missing.append("DATABASE_URI")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    load_existing_cleaner_plugin()

    app = Client(
        SESSION,
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        plugins={"root": "plugins"},
        workdir=".",
    )

    runner = None
    app_started = False
    try:
        await app.start()
        app_started = True
        bot_info = await app.get_me()
        LOGGER.info("Bot started: %s (@%s)", bot_info.first_name, bot_info.username)

        runner = await start_web_server()
        LOGGER.info("Bot is now running and listening for messages...")
        await idle()
    finally:
        LOGGER.info("Stopping bot...")
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception:
                LOGGER.exception("Web server cleanup failed")
        if app_started:
            try:
                await app.stop()
            except Exception:
                LOGGER.exception("Bot stop failed")


if __name__ == "__main__":
    asyncio.run(start_bot())
