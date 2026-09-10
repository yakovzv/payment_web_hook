from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, model_validator

from app.pkg.models.base.enum import BaseEnum

__all__ = [
    "OrderStatus", "OrderItemStatus", "CreateOrderRequest",
    "Order", "OrderView", "OrderItemView",
]


class OrderStatus(str, BaseEnum):
    created = "created"
    paid = "paid"
    delivering = "delivering"
    delivered = "delivered"                 # все строки выданы
    partially_delivered = "partially_delivered"  # часть выдана, часть возвращена
    refunded = "refunded"                   # все строки возвращены
    payment_failed = "payment_failed"
    out_of_stock = "out_of_stock"
    delivery_failed = "delivery_failed"


class OrderItemStatus(str, BaseEnum):
    created = "created"
    paid = "paid"
    delivering = "delivering"
    delivered = "delivered"
    refunded = "refunded"


# Терминальные состояния больше никогда не переходят (требование идемпотентности).
FINAL_STATUSES = {
    OrderStatus.delivered.value, OrderStatus.partially_delivered.value,
    OrderStatus.refunded.value, OrderStatus.payment_failed.value,
}
# Терминал строки: либо выдана покупателю, либо деньги за неё возвращены.
ITEM_FINAL_STATUSES = {OrderItemStatus.delivered.value, OrderItemStatus.refunded.value}


class CreateOrderRequest(BaseModel):
    """Заказ можно создать одним SKU (совместимость с этапом 1) или списком SKU.

    Списком считаются позиции по одной штуке; повтор SKU = несколько строк.
    """

    sku: Optional[str] = None
    items: Optional[List[str]] = None

    @model_validator(mode="after")
    def _one_of(self) -> "CreateOrderRequest":
        if not self.sku and not self.items:
            raise ValueError("нужно указать либо sku, либо items")
        if self.sku and self.items:
            raise ValueError("укажите либо sku, либо items, но не оба поля")
        return self

    def skus(self) -> List[str]:
        return self.items if self.items else [self.sku]


class OrderItemView(BaseModel):
    id: str
    sku: str
    amount: int
    currency: str
    status: str
    code: Optional[str] = None       # присутствует только у выданной строки
    supplier: Optional[str] = None


class Order(BaseModel):
    id: str
    sku: Optional[str] = None
    amount: int
    currency: str
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class OrderView(Order):
    """Заказ с разбивкой по строкам и (для 1-строчного заказа) с кодом наверху."""

    code: Optional[str] = None
    supplier: Optional[str] = None
    items: List[OrderItemView] = []