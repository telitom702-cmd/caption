from motor.motor_asyncio import AsyncIOMotorClient

from info import DATABASE_URI, DATABASE_NAME


if not DATABASE_URI:
    raise RuntimeError(
        "DATABASE_URI environment variable is missing!"
    )


class Database:

    def __init__(
        self,
        uri,
        database_name
    ):
        self._client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=10000
        )

        self.db = self._client[
            database_name
        ]


db = Database(
    DATABASE_URI,
    DATABASE_NAME
)
