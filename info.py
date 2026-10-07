import re
import os
from os import environ, getenv

# ============================
# Bot Information Configuration
# ============================
SESSION = environ.get('SESSION', 'royal_search')
API_ID = int(environ.get('API_ID', ''))
API_HASH = environ.get('API_HASH', '')
BOT_TOKEN = environ.get('BOT_TOKEN', '')

# ============================
# Admin & Users
# ============================
# OWNER_ID এর বদলে ADMINS লিস্ট ব্যবহার করা হচ্ছে
ADMINS = [int(admin) for admin in environ.get('ADMINS', '').split() if admin.strip()]

# ============================
# MongoDB Configuration
# ============================
DATABASE_URI = environ.get('DATABASE_URI', '')
DATABASE_NAME = environ.get('DATABASE_NAME', 'Cluster0')

# ============================
# Web Server Config
# ============================
PORT = int(environ.get("PORT", "8080"))
ON_HEROKU = 'DYNO' in environ

# ... (বাকি সব কনফিগারেশন আপনার আগের মতোই থাকবে)
