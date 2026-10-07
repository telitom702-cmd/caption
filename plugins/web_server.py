from aiohttp import web

async def web_server():
    app = web.Application()
    # একটি সাধারণ রুট যোগ করা হলো যাতে Render পিং করতে পারে
    async def handle(request):
        return web.Response(text="Bot is running!")
    
    app.router.add_get('/', handle)
    return app
