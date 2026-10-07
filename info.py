import os

SESSION = os.getenv("SESSION", "DreamxBotz")
API_ID = int(os.getenv("API_ID", "24776633"))
API_HASH = os.getenv("API_HASH", "57b1f632044b4e718f5dce004a988d69")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMINS = [int(x) for x in os.getenv("ADMINS", "8248792819").split() if x.isdigit()]
DATABASE_URI = os.getenv("DATABASE_URI", "mongodb+srv://rendamd1_db_user:M7vb8ZD9rx0AfHnP@cluster0.uzqvib6.mongodb.net/?appName=Cluster0")
DATABASE_NAME = os.getenv("DATABASE_NAME", "Cluster0")
PORT = int(os.getenv("PORT", "8080"))
