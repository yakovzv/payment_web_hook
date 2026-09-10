from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

__all__ = ["AccountBalance", "OrderItemAt", "OrderAtView", "LedgerAtView",
           "PeriodAccount", "PeriodReport"]


class AccountBalance(BaseModel):
    account: str
    debit: int
    credit: int
    balance: int          # credit - debit


class OrderItemAt(BaseModel):
    id: str
    sku: str
    amount: int
    status: str
    code: Optional[str] = None
    supplier: Optional[str] = None


class OrderAtView(BaseModel):
    order_id: str
    as_of: datetime
    exists: bool          # существовал ли заказ на этот момент
    status: str
    items: List[OrderItemAt] = []
    money: List[AccountBalance] = []   # деньги этого заказа на момент as_of


class LedgerAtView(BaseModel):
    as_of: datetime
    accounts: List[AccountBalance] = []
    balanced: bool        # сумма нетто по счетам == 0 (двойная запись)


class PeriodAccount(BaseModel):
    account: str
    opening: int          # нетто на начало периода
    closing: int          # нетто на конец периода
    debit: int            # оборот за период
    credit: int
    movement: int         # credit - debit за период
    consistent: bool      # closing == opening + movement (два независимых пути сошлись)


class PeriodReport(BaseModel):
    from_ts: datetime
    to_ts: datetime
    accounts: List[PeriodAccount] = []
    payments: int         # поступления (customer_funds credit) за период
    revenue: int          # признанная выручка (revenue credit) за период
    refunds: int          # возвраты (refunds credit) за период
    double_entry_balanced: bool   # sum(debit)==sum(credit) за период
    consistent: bool      # все счета сошлись (closing == opening + movement)
