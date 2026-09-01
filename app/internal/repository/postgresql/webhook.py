import json

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["WebhookRepo"]


class WebhookRepo(Repository):
    async def insert_event(self, conn, *, event_id, order_id, status, amount,
                           currency, payload: dict) -> bool:
        """Идемпотентная запись во входящие. True только для первого прихода
        этого event_id (ON CONFLICT DO NOTHING)."""
        row = await conn.fetchrow(
            """
            INSERT INTO webhook_events
                (event_id, order_id, status, amount, currency, payload)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
            """,
            event_id, order_id, status, amount, currency, json.dumps(payload),
        )
        return row is not None

    async def mark_processed(self, conn, event_id: str):
        await conn.execute(
            "UPDATE webhook_events SET processed=TRUE, processed_at=now() WHERE event_id=$1",
            event_id,
        )

    async def get_pending(self, limit: int):
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                """
                SELECT event_id, order_id, status, amount, currency
                FROM webhook_events
                WHERE processed = FALSE
                ORDER BY received_at
                LIMIT $1
                """,
                limit,
            )