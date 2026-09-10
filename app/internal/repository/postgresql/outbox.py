from contextlib import asynccontextmanager

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["OutboxRepo"]


@asynccontextmanager
async def _conn(conn):
    if conn is not None:
        yield conn
    else:
        async with db_instance.get_connect() as c:
            yield c


class OutboxRepo(Repository):
    async def enqueue(self, conn, item_id: str, order_id: str):
        """Поставить в очередь задачу на выдачу строки. PK item_id делает операцию
        идемпотентной (повторная постановка - no-op)."""
        await conn.execute(
            "INSERT INTO delivery_outbox (item_id, order_id) VALUES ($1, $2) "
            "ON CONFLICT (item_id) DO NOTHING",
            item_id, order_id,
        )

    async def claim_batch(self, limit: int) -> list[str]:
        """Атомарно захватить готовые задачи (SKIP LOCKED): один воркер на строку.
        Возвращает список item_id."""
        async with db_instance.get_connect() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT item_id FROM delivery_outbox
                    WHERE status='pending' AND next_attempt_at <= now()
                    ORDER BY next_attempt_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT $1
                    """,
                    limit,
                )
                ids = [r["item_id"] for r in rows]
                if ids:
                    await conn.execute(
                        "UPDATE delivery_outbox SET status='processing', locked_at=now(), "
                        "updated_at=now() WHERE item_id = ANY($1::text[])",
                        ids,
                    )
                return ids

    async def mark_done(self, item_id: str, conn=None):
        async with _conn(conn) as c:
            await c.execute(
                "UPDATE delivery_outbox SET status='done', updated_at=now() WHERE item_id=$1",
                item_id,
            )

    async def reschedule(self, item_id: str, reason: str, base: float, max_backoff: float):
        """Вернуть задачу в 'pending' с экспоненциальным бэкоффом от числа попыток."""
        async with db_instance.get_connect() as conn:
            await conn.execute(
                """
                UPDATE delivery_outbox
                SET status='pending', attempts=attempts+1, last_error=$2, locked_at=NULL,
                    next_attempt_at = now()
                        + LEAST($3 * power(2, attempts), $4) * interval '1 second',
                    updated_at=now()
                WHERE item_id=$1
                """,
                item_id, reason, base, max_backoff,
            )

    async def defer(self, item_id: str, reason: str, seconds: float):
        """Отложить задачу на короткий фиксированный интервал без инкремента attempts.
        Для бэкпрешера по лимиту: это не сбой выдачи, а ожидание ёмкости, поэтому
        экспонента не растёт, задача не теряется и вернётся, как освободится токен."""
        async with db_instance.get_connect() as conn:
            await conn.execute(
                """
                UPDATE delivery_outbox
                SET status='pending', last_error=$2, locked_at=NULL,
                    next_attempt_at = now() + $3 * interval '1 second',
                    updated_at=now()
                WHERE item_id=$1
                """,
                item_id, reason, seconds,
            )

    async def reclaim_stuck(self, stuck_sec: float) -> int:
        async with db_instance.get_connect() as conn:
            result = await conn.execute(
                """
                UPDATE delivery_outbox
                SET status='pending', locked_at=NULL, updated_at=now()
                WHERE status='processing'
                  AND locked_at < now() - ($1 * interval '1 second')
                """,
                stuck_sec,
            )
            return int(result.split()[-1]) if result.startswith("UPDATE") else 0