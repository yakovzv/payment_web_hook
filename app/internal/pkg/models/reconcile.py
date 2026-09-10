from typing import List

from pydantic import BaseModel

__all__ = ["ReconcileReport", "LedgerBalance", "IntegrityReport",
           "SupplierRate", "QueueProgress"]


class SupplierRate(BaseModel):
    supplier: str
    limit_per_window: int
    window_seconds: int
    used: int                # израсходовано токенов в текущем окне


class QueueProgress(BaseModel):
    queued: int              # оплаченных строк в очереди на выдачу (pending+processing)
    delivered: int           # уже выдано
    refunded: int            # возвращено (не удалось выдать)
    unpaid_orders: int       # заказы без оплаты (в очередь выдачи не попадают)
    rate_limits: List[SupplierRate]


class LedgerBalance(BaseModel):
    total_debit: int
    total_credit: int
    balanced: bool


class IntegrityReport(BaseModel):
    reclaimed: int      # утёкшие коды, привязанные автосверкой (без второй выдачи)
    recorded: int       # новых зафиксированных расхождений
    open_total: int     # всего открытых расхождений с поставщиком


class ReconcileReport(BaseModel):
    paid_not_delivered: List[str]      # деньги пришли, остались невыданные/невозвращённые строки
    delivered_not_paid: List[str]      # товар выдан без оплаты (должно быть пусто)
    stuck_in_delivery: List[str]       # оплачен/выдаётся, задача выдачи не завершена
    money_mismatch: List[str]          # терминальный заказ, где оплачено != выдано+возвращено (пусто)
    ledger: LedgerBalance