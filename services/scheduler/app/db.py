import json
from pathlib import Path

import asyncpg


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        database_url, min_size=1, max_size=10, init=_init_connection
    )


async def run_migrations(pool: asyncpg.Pool, migrations_dir: Path) -> None:
    async with pool.acquire() as conn:
        for path in sorted(migrations_dir.glob("*.sql")):
            await conn.execute(path.read_text())
