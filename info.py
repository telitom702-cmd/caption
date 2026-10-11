from os import environ

SESSION = environ.get("SESSION", "DreamxBotz")
API_ID = int(environ.get("API_ID", "24776633"))
API_HASH = environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMINS = [int(x) for x in environ.get("ADMINS", "8248792819").replace(",", " ").split() if x.isdigit()]
DATABASE_URI = environ.get("DATABASE_URI", "YOUR_MONGODB_URI")
DATABASE_NAME = environ.get("DATABASE_NAME", "Cluster0")
PORT = int(environ.get("PORT", "8080"))
