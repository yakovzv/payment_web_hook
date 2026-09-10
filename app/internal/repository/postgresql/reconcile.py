from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["ReconcileRepo"]

# Заказ считается «в работе» (оплачен, но не доведён), пока у него есть строка,
# которая ещё не в терминале (delivered/refunded).
_HAS_PENDING_ITEM = """
    EXISTS (SELECT 1 FROM order_items i
            WHERE i.order_id = o.id
              AND i.status NOT IN ('delivered','refunded'))
"""


class ReconcileRepo(Repository):
    async def paid_not_delivered(self) -> list[str]:
        """Оплаченные заказы, у которых остались невыданные/невозвращённые строки."""
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                f"""
                SELECT o.id FROM orders o
                WHERE o.paid_at IS NOT NULL AND {_HAS_PENDING_ITEM}
                ORDER BY o.paid_at
                """
            )
            return [r["id"] for r in rows]

    async def delivered_not_paid(self) -> list[str]:
        """Есть выдача, но заказ не оплачен - так быть не должно."""
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT o.id FROM orders o
                JOIN deliveries d ON d.order_id = o.id
                WHERE o.paid_at IS NULL
                ORDER BY o.id
                """
            )
            return [r["id"] for r in rows]

    async def stuck_in_delivery(self) -> list[str]:
        """Заказы с незакрытой задачей выдачи хотя бы по одной строке."""
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT b.order_id FROM delivery_outbox b
                JOIN order_items i ON i.id = b.item_id
                WHERE b.status <> 'done' AND i.status NOT IN ('delivered','refunded')
                ORDER BY b.order_id
                """
            )
            return [r["order_id"] for r in rows]

    async def money_mismatch(self) -> list[str]:
        """Терминальные заказы, где оплачено != выдано + возвращено.

        В журнале это значит, что счёт customer_funds заказа не обнулился:
        credit (оплата) != debit (выдачи + возвраты).
        """
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT o.id
                FROM orders o
                JOIN ledger_entries l ON l.order_id = o.id AND l.account = 'customer_funds'
                WHERE o.status IN ('delivered','partially_delivered','refunded')
                GROUP BY o.id
                HAVING COALESCE(SUM(l.amount) FILTER (WHERE l.direction='credit'), 0)
                     <> COALESCE(SUM(l.amount) FILTER (WHERE l.direction='debit'), 0)
                ORDER BY o.id
                """
            )
            return [r["id"] for r in rows]

    async def ensure_outbox_for_items(self):
        """Создать задачу выдачи для оплаченных, но ещё не выданных/не возвращённых
        строк, у которых нет ни выдачи, ни задачи в outbox (внеочередные вебхуки,
        потерянные задачи)."""
        async with db_instance.get_connect() as conn:
            await conn.execute(
                """
                INSERT INTO delivery_outbox (item_id, order_id)
                SELECT i.id, i.order_id
                FROM order_items i
                JOIN orders o ON o.id = i.order_id
                LEFT JOIN deliveries d     ON d.item_id = i.id
                LEFT JOIN delivery_outbox b ON b.item_id = i.id
                WHERE o.paid_at IS NOT NULL
                  AND i.status NOT IN ('delivered','refunded')
                  AND d.item_id IS NULL AND b.item_id IS NULL
                ON CONFLICT (item_id) DO NOTHING
                """
            )

    async def queue_progress(self):
        """Метрики прогресса: очередь / выдано / возвращено / неоплаченные."""
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                """
                SELECT
                  (SELECT count(*) FROM delivery_outbox WHERE status IN ('pending','processing'))
                      AS queued,
                  (SELECT count(*) FROM order_items WHERE status='delivered') AS delivered,
                  (SELECT count(*) FROM order_items WHERE status='refunded')  AS refunded,
                  (SELECT count(*) FROM orders WHERE status='created')        AS unpaid_orders
                """
            )

    async def requeue_recoverable(self) -> int:
        """Сделать восстановимые (не done, не processing) задачи снова готовыми."""
        async with db_instance.get_connect() as conn:
            result = await conn.execute(
                """
                UPDATE delivery_outbox b
                SET status='pending', next_attempt_at=now(), locked_at=NULL, updated_at=now()
                FROM order_items i
                WHERE b.item_id = i.id
                  AND i.status NOT IN ('delivered','refunded')
                  AND b.status NOT IN ('processing','done')
                """
            )
            return int(result.split()[-1]) if result.startswith("UPDATE") else 0
