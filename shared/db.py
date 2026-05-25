import asyncpg


async def connect_database(database_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(database_url)
