import sys
import glob
import importlib
from pathlib import Path
from pyrogram import Client, idle
import time
import asyncio
import os  # PORT এর জন্য os মডিউল জরুরি
import logging
from aiohttp import web as aiohttp_web  # নামের দ্বন্দ্ব এড়াতে alias ব্যবহার করা হলো

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ১. কনফিগারেশন ইম্পোর্ট
from info import *

# ২. ওয়েব সার্ভার ফাংশন ইম্পোর্ট
# সরাসরি ফাংশনটি ইম্পোর্ট করছি যাতে 'module' এরর না আসে
try:
    from plugins.web_server import web_server as start_web_app
except ImportError:
    logger.warning("web_server plugin not found or error importing.")
    start_web_app = None

# ৩. বট ক্লায়েন্ট সেটআপ
app = Client(
    "DreamxBotz",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

botStartTime = time.time()
ppath = "plugins/*.py"
files = glob.glob(ppath)

async def start_bot():
    print('\n\nInitializing DreamxBotz...')
    
    # বট শুরু করা
    await app.start()
    bot_info = await app.get_me()
    logger.info(f"{bot_info.first_name} started on @{bot_info.username}.")
    
    # প্লাগিন অটোমেটিক লোড করা
    for name in files:
        if "__init__" in name:
            continue
            
        with open(name) as a:
            patt = Path(a.name)
            plugin_name = patt.stem.replace(".py", "")
            plugins_dir = Path(f"plugins/{plugin_name}.py")
            
            if plugins_dir.exists():
                import_path = "plugins.{}".format(plugin_name)
                try:
                    spec = importlib.util.spec_from_file_location(import_path, plugins_dir)
                    load = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(load)
                    sys.modules["plugins." + plugin_name] = load
                    logger.info(f"DreamxBotz Imported => {plugin_name}")
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin_name}: {e}")

    # ওয়েব সার্ভার শুরু করা (Render-এর জন্য জরুরি)
    if start_web_app:
        try:
            # Render বা অন্যান্য হোস্টিং এর জন্য PORT এনভায়রনমেন্ট ভেরিয়েবল ব্যবহার করা উচিত
            port = int(os.environ.get("PORT", 8080))
            
            # web_server.py থেকে অ্যাপ অবজেক্ট পাওয়া
            web_app = await start_web_app()
            
            # aiohttp রানার সেটআপ
            runner = aiohttp_web.AppRunner(web_app)
            await runner.setup()
            
            # সার্ভার শুরু করা
            site = aiohttp_web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            
            logger.info(f"Web Server started on http://0.0.0.0:{port}")
        except Exception as e:
            logger.error(f"Web Server failed to start: {e}")
    else:
        logger.warning("Web server function not available. Skipping web server start.")
    
    logger.info("Bot is now running and listening for messages...")
    await idle()
    
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
