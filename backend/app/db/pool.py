from pathlib import Path

import asyncpg

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=10)


async def apply_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text())
