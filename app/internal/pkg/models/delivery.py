from typing import Literal, Optional

from pydantic import BaseModel

__all__ = ["IssueRequest", "IssueResponse", "SupplierOutcome", "DeliveryResult"]


class IssueRequest(BaseModel):
    request_id: str
    sku: str
    order_id: str


class IssueResponse(BaseModel):
    status: str  # ok | error (ok | ошибка)
    request_id: Optional[str] = None
    code: Optional[str] = None
    reason: Optional[str] = None


# Классификация результата одного вызова поставщика, используется для решения о fallback.
#   ok           - получен код (привязываем его)
#   out_of_stock - однозначный отказ, пробуем следующего поставщика
#   error        - однозначная ошибка поставщика (5xx после повторов), пробуем следующего
#   timeout      - неоднозначно (код мог быть выдан): не делаем fallback, повторяем с тем же rid
SupplierOutcome = Literal["ok", "out_of_stock", "error", "timeout"]


class DeliveryResult(BaseModel):
    order_id: str
    item_id: Optional[str] = None
    delivered: bool
    refunded: bool = False
    supplier: Optional[str] = None
    code: Optional[str] = None
    status: str
    detail: Optional[str] = None