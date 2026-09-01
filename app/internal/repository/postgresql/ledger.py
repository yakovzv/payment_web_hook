from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["LedgerRepo"]


class LedgerRepo(Repository):
    async def book_payment(self, conn, *, order_id, event_id, amount, currency):
        """Проводка двойной записи: дебет по cash, кредит по revenue. Идемпотентно по событию."""
        await conn.execute(
            """
            INSERT INTO ledger_entries (order_id, event_id, account, direction, amount, currency)
            VALUES ($1, $2, 'cash', 'debit', $3, $4),
                   ($1, $2, 'revenue', 'credit', $3, $4)
            ON CONFLICT (event_id, account, direction) DO NOTHING
            """,
            order_id, event_id, amount, currency,
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