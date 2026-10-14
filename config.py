import os


def _int_env(name, default=0):
    """Read an integer environment setting without failing during import."""
    value = os.environ.get(name, str(default)).strip()
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Config:
    API_ID = _int_env("API_ID")
    API_HASH = os.environ.get("API_HASH", "").strip()
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
    BOT_SESSION = os.environ.get("BOT_SESSION", "vjbot").strip() or "vjbot"
    DATABASE_URI = os.environ.get("DATABASE_URI", "").strip()
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "vj-forward-bot").strip() or "vj-forward-bot"
    BOT_OWNER = _int_env("BOT_OWNER")


class temp:
    lock = {}
    CANCEL = {}
    forwardings = 0
    BANNED_USERS = []
    IS_FRWD_CHAT = []


PORT = _int_env("PORT", 8080)
