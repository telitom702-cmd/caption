from os import environ

# Keep credentials in the deployment environment, never in source control.
SESSION = environ.get("SESSION", "DreamZBotz")
API_ID = int(environ.get("API_ID", "0"))
API_HASH = environ.get("API_HASH", "").strip()
BOT_TOKEN = environ.get("BOT_TOKEN", "").strip()
HISTORY_SESSION = environ.get("HISTORY_SESSION", "").strip()
ADMINS = [
    int(x)
    for x in environ.get("ADMINS", "").replace(",", " ").split()
    if x.isdigit()
]
DATABASE_URI = environ.get("DATABASE_URI", "").strip()
DATABASE_NAME = environ.get("DATABASE_NAME", "Cluster0")
PORT = int(environ.get("PORT", "8080"))
