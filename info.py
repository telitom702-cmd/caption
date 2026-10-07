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
API_ID = _int_env("API_ID", 24776633)
API_HASH = os.getenv("API_HASH", "57b1f632044b4e718f5dce004a988d69").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMINS = [
    int(value)
    for value in os.getenv("ADMINS", "8248792819").replace(",", " ").split()
    if value.isdigit()
]
DATABASE_URI = os.getenv("DATABASE_URI", "mongodb+srv://rendamd1_db_user:M7vb8ZD9rx0AfHnP@cluster0.uzqvib6.mongodb.net/?appName=Cluster0").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "Cluster0")
PORT = _int_env("PORT", 8080)
