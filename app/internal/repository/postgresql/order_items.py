"""Строки заказа: независимый жизненный цикл каждой позиции + пересчёт
производного статуса заказа-агрегата. Все переходы guarded (WHERE status=...),
поэтому идемпотентны и безопасны при повторах/восстановлении."""

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["OrderItemRepo"]


class OrderItemRepo(Repository):
    async def create_many(self, conn, order_id: str, items: list[dict]) -> None:
        """Массовая вставка строк заказа в транзакции создания заказа."""
        await conn.executemany(
            """
            INSERT INTO order_items (id, order_id, sku, amount, currency, status)
            VALUES ($1, $2, $3, $4, $5, 'created')
            """,
            [(it["id"], order_id, it["sku"], it["amount"], it["currency"]) for it in items],
        )

    async def list_for_order(self, order_id: str):
        """Строки заказа с кодом выдачи (LEFT JOIN deliveries)."""
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
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

    async def get_basic(self, item_id: str):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                "SELECT id, order_id, sku, amount, currency, status "
                "FROM order_items WHERE id=$1",
                item_id,
            )

    async def ids_for_order(self, conn, order_id: str) -> list[str]:
        rows = await conn.fetch(
            "SELECT id FROM order_items WHERE order_id=$1 ORDER BY created_at, id",
            order_id,
        )
        return [r["id"] for r in rows]

    async def mark_paid(self, conn, order_id: str) -> None:
        """Перевод created в paid для всех строк заказа при проведении оплаты."""
        await conn.execute(
            "UPDATE order_items SET status='paid', updated_at=now() "
            "WHERE order_id=$1 AND status='created'",
            order_id,
        )

    async def set_status(self, conn, item_id: str, status: str) -> None:
        """Нефинальный статус строки; терминал (delivered/refunded) не перезаписываем."""
        await conn.execute(
            "UPDATE order_items SET status=$2, updated_at=now() "
            "WHERE id=$1 AND status NOT IN ('delivered','refunded')",
            item_id, status,
        )

    async def mark_delivered(self, conn, item_id: str) -> None:
        await conn.execute(
            "UPDATE order_items SET status='delivered', updated_at=now() "
            "WHERE id=$1 AND status <> 'delivered'",
            item_id,
        )

    async def transition_to_refunded(self, conn, item_id: str):
        """Guarded-переход в refunded. Возвращает строку, только если возврат
        оформил именно этот вызов (иначе no-op), что даёт ровно один возврат."""
        return await conn.fetchrow(
            """
            UPDATE order_items SET status='refunded', updated_at=now()
            WHERE id=$1 AND status NOT IN ('delivered','refunded')
            RETURNING id, order_id, amount, currency
            """,
            item_id,
        )

    async def recompute_order_status(self, conn, order_id: str) -> None:
        """Пересчитать производный статус заказа из статусов его строк.

        Все строки терминальны: delivered / refunded / partially_delivered.
        Иначе (оплачен, есть незавершённые строки): delivering.
        payment_failed и ещё не оплаченный created не трогаем.
        """
        await conn.execute(
            """
            UPDATE orders o
            SET status = CASE
                    WHEN EXISTS (SELECT 1 FROM order_items i
                                 WHERE i.order_id=o.id
                                   AND i.status NOT IN ('delivered','refunded'))
                        THEN 'delivering'
                    WHEN NOT EXISTS (SELECT 1 FROM order_items i
                                     WHERE i.order_id=o.id AND i.status='refunded')
                        THEN 'delivered'
                    WHEN NOT EXISTS (SELECT 1 FROM order_items i
                                     WHERE i.order_id=o.id AND i.status='delivered')
                        THEN 'refunded'
                    ELSE 'partially_delivered'
                END,
                delivered_at = CASE
                    WHEN NOT EXISTS (SELECT 1 FROM order_items i
                                     WHERE i.order_id=o.id
                                       AND i.status NOT IN ('delivered','refunded'))
                        THEN now() ELSE o.delivered_at
                END,
                updated_at = now()
            WHERE o.id=$1
              AND o.status IN ('paid','delivering','delivered',
                               'partially_delivered','refunded')
            """,
            order_id,
        )