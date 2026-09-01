from typing import List

from pydantic import BaseModel

__all__ = ["ReconcileReport", "LedgerBalance"]


class LedgerBalance(BaseModel):
    total_debit: int
    total_credit: int
    balanced: bool


class ReconcileReport(BaseModel):
    paid_not_delivered: List[str]      # деньги пришли, товар не выдан
    delivered_not_paid: List[str]      # товар выдан без оплаты (должно быть пусто)
    stuck_in_delivery: List[str]       # оплачен/выдаётся, задача выдачи не завершена
    ledger: LedgerBalance