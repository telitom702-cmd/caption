from motor.motor_asyncio import AsyncIOMotorClient
from plugins.config import Config

client = AsyncIOMotorClient(Config.DATABASE_URL)
db = client[Config.DATABASE_NAME]
