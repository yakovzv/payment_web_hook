from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["LedgerRepo"]


class LedgerRepo(Repository):
    async def book_payment(self, conn, *, order_id, event_id, amount, currency):
        """Оплата заказа: debit cash, credit customer_funds (обязательство перед
        покупателем). Идемпотентно по (event_id, account, direction)."""
        await conn.execute(
            """
            INSERT INTO ledger_entries (order_id, event_id, account, direction, amount, currency)
            VALUES ($1, $2, 'cash', 'debit', $3, $4),
                   ($1, $2, 'customer_funds', 'credit', $3, $4)
            ON CONFLICT (event_id, account, direction) DO NOTHING
            """,
            order_id, event_id, amount, currency,
        )

    async def book_delivery(self, conn, *, item_id, order_id, amount, currency):
        """Строка выдана: debit customer_funds, credit revenue (признание выручки).
        Синтетический event_id = 'deliver:<item_id>' даёт ровно одну проводку на строку."""
        await conn.execute(
            """
            INSERT INTO ledger_entries (order_id, event_id, account, direction, amount, currency)
            VALUES ($1, $2, 'customer_funds', 'debit', $3, $4),
                   ($1, $2, 'revenue', 'credit', $3, $4)
            ON CONFLICT (event_id, account, direction) DO NOTHING
            """,
            order_id, f"deliver:{item_id}", amount, currency,
        )

    async def book_refund(self, conn, *, item_id, order_id, amount, currency):
        """Строка возвращена: debit customer_funds, credit refunds (деньги назад).
        Синтетический event_id = 'refund:<item_id>' даёт ровно один возврат на строку."""
        await conn.execute(
            """
            INSERT INTO ledger_entries (order_id, event_id, account, direction, amount, currency)
            VALUES ($1, $2, 'customer_funds', 'debit', $3, $4),
                   ($1, $2, 'refunds', 'credit', $3, $4)
            ON CONFLICT (event_id, account, direction) DO NOTHING
            """,
            order_id, f"refund:{item_id}", amount, currency,
        )

    async def balance(self):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(amount) FILTER (WHERE direction='debit'), 0)  AS total_debit,
                  COALESCE(SUM(amount) FILTER (WHERE direction='credit'), 0) AS total_credit
                FROM ledger_entries
                """
            )

    async def balances_asof(self, ts, order_id=None):
        """Остатки по счетам на момент ts (created_at <= ts), опц. по одному заказу.
        Реконструкция денег «на прошлую дату» из append-only журнала."""
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                """
                SELECT account,
                  COALESCE(SUM(amount) FILTER (WHERE direction='debit'), 0)  AS debit,
                  COALESCE(SUM(amount) FILTER (WHERE direction='credit'), 0) AS credit
                FROM ledger_entries
                WHERE created_at <= $1 AND ($2::text IS NULL OR order_id = $2)
                GROUP BY account
                ORDER BY account
                """,
                ts, order_id,
            )

    async def movements(self, dt_from, dt_to):
        """Движения по счетам за период (dt_from, dt_to] - для итогов за период."""
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                """
                SELECT account,
                  COALESCE(SUM(amount) FILTER (WHERE direction='debit'), 0)  AS debit,
                  COALESCE(SUM(amount) FILTER (WHERE direction='credit'), 0) AS credit
                FROM ledger_entries
                WHERE created_at > $1 AND created_at <= $2
                GROUP BY account
                ORDER BY account
                """,
                dt_from, dt_to,
            )