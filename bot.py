import sys
import glob
import importlib
from pathlib import Path
from pyrogram import Client, idle
import time
import asyncio
from aiohttp import web
import logging

# লগিং সেটআপ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ১. কনফিগারেশন ইম্পোর্ট (আপনার info.py থেকে)
from info import *

# ২. প্লাগিন ফোল্ডার থেকে ওয়েব সার্ভার ইম্পোর্ট (যদি plugins/web_server.py থাকে)
try:
    from plugins import web_server
except ImportError:
    logger.warning("web_server plugin not found or error importing.")
    web_server = None

# ৩. বট ক্লায়েন্ট সেটআপ (Pyrogram)
# নোট: dreamxbotz ফোল্ডার না থাকায় আমরা সরাসরি এখানে ক্লায়েন্ট তৈরি করছি
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
        # __init__.py বা অনাকাঙ্ক্ষিত ফাইল বাদ দেওয়া
        if "__init__" in name:
            continue
            
        with open(name) as a:
            patt = Path(a.name)
            plugin_name = patt.stem.replace(".py", "")
            plugins_dir = Path(f"plugins/{plugin_name}.py")
            
            # যদি ফাইলটি আসলেই exists করে
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
    if web_server:
        try:
            # web_server ফাংশনটি একটি app রিটার্ন করে কিনা চেক করতে হবে
            # সাধারণত এটি একটি aiohttp web.Application রিটার্ন করে
            app_runner = web.AppRunner(await web_server()) 
            await app_runner.setup()
            bind_address = "0.0.0.0"
            await web.TCPSite(app_runner, bind_address, PORT).start()
            logger.info(f"Web Server started on http://{bind_address}:{PORT}")
        except Exception as e:
            logger.error(f"Web Server failed to start: {e}")
    
    logger.info("Bot is now running and listening for messages...")
    await idle()
    
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())
