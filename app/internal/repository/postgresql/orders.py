from app.internal.pkg.connectors import db_instance
from app.internal.pkg.models.order import Order, OrderView
from app.internal.repository.handlers.collect_response import collect_response
from app.internal.repository.repository import Repository

__all__ = ["OrderRepo"]


class OrderRepo(Repository):
    @collect_response
    async def create(self, order_id: str, sku: str, amount: int, currency: str) -> Order:
        async with db_instance.get_connect() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO orders (id, sku, amount, currency, status)
                VALUES ($1, $2, $3, $4, 'created')
                RETURNING id, sku, amount, currency, status,
                          created_at, paid_at, delivered_at
                """,
                order_id,
                sku,
                amount,
                currency,
            )
            return row

    @collect_response(nullable=True)
    async def get(self, order_id: str) -> OrderView:
        """Заказ, соединённый с выданным кодом (code равен NULL до момента выдачи)."""
        async with db_instance.get_connect() as conn:
            row = await conn.fetchrow(
                """
                SELECT o.id, o.sku, o.amount, o.currency, o.status,
                       o.created_at, o.paid_at, o.delivered_at,
                       d.code, d.supplier
                FROM orders o
                LEFT JOIN deliveries d ON d.order_id = o.id
                WHERE o.id = $1
                """,
                order_id,
            )
            return row

    async def get_basic(self, order_id: str):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                "SELECT id, sku, status FROM orders WHERE id=$1", order_id
            )

    # ---- транзакционные (используют соединение вызывающей стороны) -----------

    async def lock(self, conn, order_id: str):
        """Заблокировать строку заказа для сериализованного перехода состояния."""
        return await conn.fetchrow(
            "SELECT id, amount, currency, status FROM orders WHERE id=$1 FOR UPDATE",
            order_id,
        )

    async def transition_to_paid(self, conn, order_id: str):
        """created -> paid. Возвращает строку только если переход выполнил именно этот вызов."""
        return await conn.fetchrow(
            """
            UPDATE orders SET status='paid', paid_at=now(), updated_at=now()
            WHERE id=$1 AND status='created'
            RETURNING id, amount, currency
            """,
            order_id,
        )

    async def transition_to_payment_failed(self, conn, order_id: str):
        return await conn.fetchrow(
            """
            UPDATE orders SET status='payment_failed', updated_at=now()
            WHERE id=$1 AND status='created'
            RETURNING id
            """,
            order_id,
        )

    async def set_status(self, conn, order_id: str, status: str):
        """Установить нефинальный статус; никогда не перезаписывать терминальное состояние."""
        await conn.execute(
            "UPDATE orders SET status=$2, updated_at=now() "
            "WHERE id=$1 AND status NOT IN ('delivered','payment_failed')",
            order_id, status,
        )

    async def mark_delivered(self, conn, order_id: str):
        await conn.execute(
            "UPDATE orders SET status='delivered', delivered_at=now(), updated_at=now() "
            "WHERE id=$1",
            order_id,
        )