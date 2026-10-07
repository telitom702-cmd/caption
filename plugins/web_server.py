from aiohttp import web


async def web_server():
    app = web.Application()

    async def handle(request):
        return web.Response(
            text="DreamxBotz is running!"
        )

    async def health(request):
        return web.Response(
            text="OK"
        )

    app.router.add_get("/", handle)
    app.router.add_get("/health", health)

    return app
