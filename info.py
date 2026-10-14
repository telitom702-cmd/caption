from os import environ


def _int_env(name, default=0):
    value = environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


SESSION = environ.get("SESSION", "DreamxBotz")
API_ID = _int_env("API_ID")
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
ADMINS = [int(x) for x in environ.get("ADMINS", "").replace(",", " ").split() if x.isdigit()]
OWNER_ID = _int_env("OWNER_ID", ADMINS[0] if ADMINS else 0)
DATABASE_URI = environ.get("DATABASE_URI", "").strip()
DATABASE_NAME = environ.get("DATABASE_NAME", "Cluster0")
PORT = _int_env("PORT", 8080)
