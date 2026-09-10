from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["RateLimitRepo"]


class RateLimitRepo(Repository):
    async def try_acquire(self, supplier: str) -> bool:
        """Атомарно взять один токен в текущем окне поставщика. Счётчик общий в БД,
        поэтому лимит соблюдается всеми воркерами/процессами сразу. Возвращает False,
        если окно исчерпано; при limit_per_window=0 всегда False (поставщик заблокирован)."""
        async with db_instance.get_connect() as conn:
            async with conn.transaction():
                # UPDATE берёт блокировку строки и заодно сбрасывает окно, если оно истекло.
                row = await conn.fetchrow(
                    """
                    UPDATE supplier_rate_limit
                    SET window_start = CASE
                            WHEN now() - window_start >= window_seconds * interval '1 second'
                            THEN now() ELSE window_start END,
                        used = CASE
                            WHEN now() - window_start >= window_seconds * interval '1 second'
                            THEN 0 ELSE used END
                    WHERE supplier = $1
                    RETURNING limit_per_window, used
                    """,
                    supplier,
                )
                if row is None:
                    return True  # лимит не сконфигурирован, не ограничиваем
                if row["used"] >= row["limit_per_window"]:
                    return False
                await conn.execute(
                    "UPDATE supplier_rate_limit SET used = used + 1 WHERE supplier = $1",
                    supplier,
                )
                return True

    async def set_limit(self, supplier: str, limit_per_window: int, window_seconds: int):
        """Задать лимит и сбросить окно (используется тестами/эксплуатацией)."""
        async with db_instance.get_connect() as conn:
            await conn.execute(
                """
                INSERT INTO supplier_rate_limit
                    (supplier, limit_per_window, window_seconds, window_start, used)
                VALUES ($1, $2, $3, now(), 0)
                ON CONFLICT (supplier) DO UPDATE
                SET limit_per_window = EXCLUDED.limit_per_window,
                    window_seconds   = EXCLUDED.window_seconds,
                    window_start     = now(),
                    used             = 0
                """,
                supplier, limit_per_window, window_seconds,
            )

    async def usage(self):
        """Срез по всем поставщикам: сколько токенов израсходовано в текущем окне."""
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                """
                SELECT supplier, limit_per_window, window_seconds,
                       CASE WHEN now() - window_start >= window_seconds * interval '1 second'
                            THEN 0 ELSE used END AS used
                FROM supplier_rate_limit
                ORDER BY supplier
                """
            )
