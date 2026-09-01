from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.pkg.models.base.enum import BaseEnum

__all__ = ["OrderStatus", "CreateOrderRequest", "Order", "OrderView"]


class OrderStatus(str, BaseEnum):
    created = "created"
    paid = "paid"
    delivering = "delivering"
    delivered = "delivered"
    payment_failed = "payment_failed"
    out_of_stock = "out_of_stock"
    delivery_failed = "delivery_failed"


# Терминальные состояния больше никогда не переходят (требование идемпотентности).
FINAL_STATUSES = {OrderStatus.delivered.value, OrderStatus.payment_failed.value}


class CreateOrderRequest(BaseModel):
    sku: str


class Order(BaseModel):
    id: str
    sku: str
    amount: int
    currency: str
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class OrderView(Order):
    """Заказ, дополненный выданным кодом (присутствует только после доставки)."""

    code: Optional[str] = None
    supplier: Optional[str] = None