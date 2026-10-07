import sys
import glob
import importlib
from pathlib import Path
from pyrogram import Client, idle, __version__
import time
import asyncio
from aiohttp import web
from info import *
from utils import temp
from Script import script
from plugins import web_server # Ensure this plugin exists or remove if not needed
from dreamxbotz.Bot import dreamxbotz # Assuming your bot client name
from dreamxbotz.Bot.clients import initialize_clients

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

botStartTime = time.time()
ppath = "plugins/*.py"
files = glob.glob(ppath)

async def dreamxbotz_start():
    print('\n\nInitializing DreamxBotz with Auto Cleaner...')
    await dreamxbotz.start()
    bot_info = await dreamxbotz.get_me()
    dreamxbotz.username = bot_info.username
    await initialize_clients()
    
    # Load Plugins Automatically
    for name in files:
        with open(name) as a:
            patt = Path(a.name)
            plugin_name = patt.stem.replace(".py", "")
            plugins_dir = Path(f"plugins/{plugin_name}.py")
            import_path = "plugins.{}".format(plugin_name)
            spec = importlib.util.spec_from_file_location(import_path, plugins_dir)
            load = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(load)
            sys.modules["plugins." + plugin_name] = load
            print(f"DreamxBotz Imported => {plugin_name}")

    logger.info(f"{bot_info.first_name} started on {bot_info.username}.")
    
    # Start Web Server
    app = web.AppRunner(await web_server()) # Make sure web_server plugin returns an app
    await app.setup()
    bind_address = "0.0.0.0"
    await web.TCPSite(app, bind_address, PORT).start()
    logger.info(f"Web Server started on http://{bind_address}:{PORT}")
    
    await idle()
    
if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(dreamxbotz_start())
