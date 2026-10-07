import os

SESSION = os.getenv("SESSION", "DreamxBotz")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

ADMINS = [
    int(x) for x in os.getenv("ADMINS", "").split()
    if x.isdigit()
]

DATABASE_URI = os.getenv("DATABASE_URI", "")
DATABASE_NAME = os.getenv("DATABASE_NAME", "Cluster0")

PORT = int(os.getenv("PORT", "8080"))
ON_HEROKU = "DYNO" in os.environ
