from app.internal.pkg.connectors import db_instance
from app.internal.pkg.models.order import OrderView
from app.internal.repository.handlers.collect_response import collect_response
from app.internal.repository.repository import Repository

__all__ = ["OrderRepo"]


class OrderRepo(Repository):
    async def create_header(self, conn, order_id: str, sku, amount: int, currency: str):
        """Вставить заголовок заказа-агрегата в транзакции создания.

        sku заполняется для 1-строчного заказа (совместимость с этапом 1) и
        равен NULL для мультитоварного; amount - сумма строк.
        """
        return await conn.fetchrow(
            """
            INSERT INTO orders (id, sku, amount, currency, status)
            VALUES ($1, $2, $3, $4, 'created')
            RETURNING id, sku, amount, currency, status,
                      created_at, paid_at, delivered_at
            """,
            order_id, sku, amount, currency,
        )

    @collect_response(nullable=True)
    async def get(self, order_id: str) -> OrderView:
        """Заказ + разбивка по строкам. Для 1-строчного заказа код/поставщик
        дублируются на верхний уровень (совместимость с этапом 1)."""
        async with db_instance.get_connect() as conn:
            order = await conn.fetchrow(
                """
                SELECT o.id, o.sku, o.amount, o.currency, o.status,
                       o.created_at, o.paid_at, o.delivered_at
                FROM orders o
                WHERE o.id = $1
                """,
                order_id,
            )
            if order is None:
                return None
            items = await conn.fetch(
                """
                SELECT i.id, i.sku, i.amount, i.currency, i.status,
                       d.code, d.supplier
                FROM order_items i
                LEFT JOIN deliveries d ON d.item_id = i.id
                WHERE i.order_id = $1
                ORDER BY i.created_at, i.id
                """,
                order_id,
            )
            view = dict(order)
            view["items"] = [dict(r) for r in items]
            # Верхнеуровневые code/supplier - только когда в заказе ровно одна строка.
            if len(items) == 1:
                view["code"] = items[0]["code"]
                view["supplier"] = items[0]["supplier"]
            return view

    async def get_basic(self, order_id: str):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                "SELECT id, sku, status FROM orders WHERE id=$1", order_id
            )

    async def lock(self, conn, order_id: str):
        """Заблокировать строку заказа для сериализованного перехода состояния."""
        return await conn.fetchrow(
            "SELECT id, amount, currency, status FROM orders WHERE id=$1 FOR UPDATE",
            order_id,
        )

    async def transition_to_paid(self, conn, order_id: str):
        """Перевод created в paid. Возвращает строку, только если переход выполнил этот вызов."""
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

    async def mark_delivering(self, conn, order_id: str):
        """Перевод paid в delivering при старте выдачи (нефинальный, терминал не трогаем)."""
        await conn.execute(
            "UPDATE orders SET status='delivering', updated_at=now() "
            "WHERE id=$1 AND status='paid'",
            order_id,
        )