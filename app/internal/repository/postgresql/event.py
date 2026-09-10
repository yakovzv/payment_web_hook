import json

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["EventRepo"]


class EventRepo(Repository):
    async def append(self, conn, *, order_id: str, type: str,
                     item_id: str = None, payload: dict = None) -> None:
        """Дописать неизменяемое событие в историю (в транзакции самого перехода).
        Пишется ровно на реальном guarded-переходе, поэтому событие не дублируется."""
        await conn.execute(
            "INSERT INTO order_events (order_id, item_id, type, payload) "
            "VALUES ($1, $2, $3, $4)",
            order_id, item_id, type, json.dumps(payload or {}),
        )

    async def for_order_asof(self, order_id: str, ts):
        """События заказа не позже момента ts, в порядке возникновения."""
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                """
                SELECT id, order_id, item_id, type, payload, occurred_at
                FROM order_events
                WHERE order_id = $1 AND occurred_at <= $2
                ORDER BY occurred_at, id
                """,
                order_id, ts,
            )
