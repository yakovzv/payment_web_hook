"""Unit of Work: сервис держит границу транзакции, а весь SQL — в репозиториях."""

from contextlib import asynccontextmanager

from app.internal.pkg.connectors import db_instance

__all__ = ["transaction"]


@asynccontextmanager
async def transaction():
    async with db_instance.get_connect() as conn:
        async with conn.transaction():
            yield conn