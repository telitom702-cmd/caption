import os


def _int_env(name, default):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


SESSION = os.getenv("SESSION", "DreamxBotz")
API_ID = _int_env("API_ID", 0)
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMINS = [
    int(value)
    for value in os.getenv("ADMINS", "").replace(",", " ").split()
    if value.isdigit()
]
DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "Cluster0")
PORT = _int_env("PORT", 8080)
