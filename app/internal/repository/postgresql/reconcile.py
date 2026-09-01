from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["ReconcileRepo"]


class ReconcileRepo(Repository):
    async def paid_not_delivered(self) -> list[str]:
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT o.id FROM orders o
                LEFT JOIN deliveries d ON d.order_id = o.id
                WHERE o.paid_at IS NOT NULL AND o.status <> 'delivered' AND d.order_id IS NULL
                ORDER BY o.paid_at
                """
            )
            return [r["id"] for r in rows]

    async def delivered_not_paid(self) -> list[str]:
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT o.id FROM orders o
                JOIN deliveries d ON d.order_id = o.id
                WHERE o.paid_at IS NULL
                ORDER BY o.id
                """
            )
            return [r["id"] for r in rows]

    async def stuck_in_delivery(self) -> list[str]:
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT o.id FROM orders o
                JOIN delivery_outbox b ON b.order_id = o.id
                WHERE b.status <> 'done' AND o.status <> 'delivered'
                ORDER BY b.created_at
                """
            )
            return [r["id"] for r in rows]

    async def ensure_outbox_for_paid(self):
        """Создать задачу выдачи для оплаченных, но не выданных заказов без задачи."""
        async with db_instance.get_connect() as conn:
            await conn.execute(
                """
                INSERT INTO delivery_outbox (order_id)
                SELECT o.id FROM orders o
                LEFT JOIN deliveries d ON d.order_id = o.id
                LEFT JOIN delivery_outbox b ON b.order_id = o.id
                WHERE o.paid_at IS NOT NULL AND o.status <> 'delivered'
                  AND d.order_id IS NULL AND b.order_id IS NULL
                ON CONFLICT (order_id) DO NOTHING
                """
            )

    async def requeue_recoverable(self) -> int:
        """Make recoverable (non-done, non-processing) jobs due again now."""
        async with db_instance.get_connect() as conn:
            result = await conn.execute(
                """
                UPDATE delivery_outbox b
                SET status='pending', next_attempt_at=now(), locked_at=NULL, updated_at=now()
                FROM orders o
                WHERE b.order_id = o.id
                  AND o.status <> 'delivered'
                  AND b.status NOT IN ('processing','done')
                """
            )
            return int(result.split()[-1]) if result.startswith("UPDATE") else 0