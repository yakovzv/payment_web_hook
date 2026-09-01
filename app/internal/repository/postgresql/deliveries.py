import asyncpg

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["DeliveryRepo"]


class DeliveryRepo(Repository):
    async def get(self, order_id: str):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                "SELECT supplier, code FROM deliveries WHERE order_id=$1", order_id
            )

    async def bind(self, conn, *, order_id, supplier, request_id, code) -> bool:
        """Вставить выданный код. Возвращает False, если у заказа уже есть код
        (первичный ключ order_id — жёсткая гарантия exactly-once) или код уже занят."""
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO deliveries (order_id, supplier, request_id, code)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (order_id) DO NOTHING
                RETURNING order_id
                """,
                order_id, supplier, request_id, code,
            )
        except asyncpg.UniqueViolationError:
            # Тот же код уже привязан к другому заказу (ошибка поставщика).
            return False
        return row is not None