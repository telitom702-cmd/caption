import os
from os import environ


# ============================
# Bot Configuration
# ============================

SESSION = environ.get(
    "SESSION",
    "DreamxBotz"
)

API_ID = int(
    environ.get(
        "API_ID",
        "0"
    )
)

API_HASH = environ.get(
    "API_HASH",
    ""
)

BOT_TOKEN = environ.get(
    "BOT_TOKEN",
    ""
)


# ============================
# Admin
# ============================

ADMINS = [
    int(admin)
    for admin in environ.get(
        "ADMINS",
        ""
    ).split()
    if admin.strip().isdigit()
]


# ============================
# MongoDB
# ============================

DATABASE_URI = environ.get(
    "DATABASE_URI",
    ""
)

DATABASE_NAME = environ.get(
    "DATABASE_NAME",
    "Cluster0"
)


# ============================
# Web Server
# ============================

PORT = int(
    environ.get(
        "PORT",
        "8080"
    )
)

ON_HEROKU = "DYNO" in environ
