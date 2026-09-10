"""Сверка (оплачен-не-выдан / выдан-не-оплачен + баланс журнала) и безопасное
восстановление зависших заказов."""

from app.internal.pkg.models.reconcile import (LedgerBalance, QueueProgress,
                                               ReconcileReport, SupplierRate)
from app.internal.repository.postgresql.ledger import LedgerRepo
from app.internal.repository.postgresql.rate_limit import RateLimitRepo
from app.internal.repository.postgresql.reconcile import ReconcileRepo
from app.pkg.logger.events import log_event

__all__ = ["ReconcileService"]


class ReconcileService:
    def __init__(self, reconcile_repo: ReconcileRepo, ledger_repo: LedgerRepo,
                 rate_limit_repo: RateLimitRepo):
        self.reconcile_repo = reconcile_repo
        self.ledger_repo = ledger_repo
        self.rate_limit_repo = rate_limit_repo

    async def reconcile(self) -> ReconcileReport:
        paid_not_delivered = await self.reconcile_repo.paid_not_delivered()
        delivered_not_paid = await self.reconcile_repo.delivered_not_paid()
        stuck = await self.reconcile_repo.stuck_in_delivery()
        money_mismatch = await self.reconcile_repo.money_mismatch()
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
            money_mismatch=money_mismatch,
            ledger=balance,
        )

    async def queue_progress(self) -> QueueProgress:
        row = await self.reconcile_repo.queue_progress()
        rates = await self.rate_limit_repo.usage()
        return QueueProgress(
            queued=row["queued"],
            delivered=row["delivered"],
            refunded=row["refunded"],
            unpaid_orders=row["unpaid_orders"],
            rate_limits=[
                SupplierRate(supplier=r["supplier"], limit_per_window=r["limit_per_window"],
                             window_seconds=r["window_seconds"], used=r["used"])
                for r in rates
            ],
        )

    async def set_rate_limit(self, supplier: str, limit_per_window: int, window_seconds: int):
        await self.rate_limit_repo.set_limit(supplier, limit_per_window, window_seconds)

    async def recover(self) -> int:
        await self.reconcile_repo.ensure_outbox_for_items()
        count = await self.reconcile_repo.requeue_recoverable()
        if count:
            log_event("Восстановление: строки переставлены в очередь", count=count)
        return count