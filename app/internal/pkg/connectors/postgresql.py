from contextlib import asynccontextmanager

import asyncpg
import pydantic
from asyncpg import Connection

from app.pkg.connectors.base_connector import BaseConnector


__all__ = ["Postgresql"]


class Postgresql(BaseConnector):
    def __init__(
        self,
        username: str,
        password: str,
        host: pydantic.PositiveInt,
        port: pydantic.PositiveInt,
        database_name: str,
        min_size: int = 10,
        max_size: int = 100,
        timeout: int = 60,
    ):
        self.pool = None
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.database_name = database_name
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout

    def get_dsn(self):
        return (
            f"postgresql://"
            f"{self.username}:"
            f"{self.password}@"
            f"{self.host}:{self.port}/"
            f"{self.database_name}"
        )

    @asynccontextmanager
    async def get_connect(self) -> Connection:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                dsn=self.get_dsn(),
                min_size=self.min_size,
                max_size=self.max_size,
            )

        async with self.pool.acquire() as conn:
            yield conn
