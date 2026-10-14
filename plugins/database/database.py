from motor.motor_asyncio import AsyncIOMotorClient
from info import info

client = AsyncIOMotorClient(info.DATABASE_URL)
db = client[info.DATABASE_NAME]
