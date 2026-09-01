"""Сверка (оплачен-не-выдан / выдан-не-оплачен + баланс журнала) и безопасное
восстановление зависших заказов."""

from app.internal.pkg.models.reconcile import LedgerBalance, ReconcileReport
from app.internal.repository.postgresql.ledger import LedgerRepo
from app.internal.repository.postgresql.reconcile import ReconcileRepo
from app.pkg.logger.events import log_event

__all__ = ["ReconcileService"]


class ReconcileService:
    def __init__(self, reconcile_repo: ReconcileRepo, ledger_repo: LedgerRepo):
        self.reconcile_repo = reconcile_repo
        self.ledger_repo = ledger_repo

    async def reconcile(self) -> ReconcileReport:
        paid_not_delivered = await self.reconcile_repo.paid_not_delivered()
        delivered_not_paid = await self.reconcile_repo.delivered_not_paid()
        stuck = await self.reconcile_repo.stuck_in_delivery()
        totals = await self.ledger_repo.balance()

        balance = LedgerBalance(
            total_debit=totals["total_debit"],
            total_credit=totals["total_credit"],
            balanced=totals["total_debit"] == totals["total_credit"],
        )
        return ReconcileReport(
            paid_not_delivered=paid_not_delivered,
            delivered_not_paid=delivered_not_paid,
            stuck_in_delivery=stuck,
            ledger=balance,
        )

    async def recover(self) -> int:
        await self.reconcile_repo.ensure_outbox_for_paid()
        count = await self.reconcile_repo.requeue_recoverable()
        if count:
            log_event("Восстановление: заказы переставлены в очередь", count=count)
        return count