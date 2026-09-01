from datetime import datetime
from typing import Optional

from pydantic import BaseModel

__all__ = ["PaymentWebhook", "WebhookAck"]


class PaymentWebhook(BaseModel):
    """Полезная нагрузка, доставляемая платёжной системой (см. контракт вебхука)."""

    event_id: str
    order_id: str
    status: str  # paid | failed (оплачено | неуспешно)
    amount: Optional[int] = None
    currency: Optional[str] = None
    created_at: Optional[datetime] = None


class WebhookAck(BaseModel):
    accepted: bool = True
    # applied  -> событие изменило состояние заказа сейчас
    # duplicate-> event_id уже встречался, операция без эффекта
    # pending  -> сохранено, но заказа ещё нет (будет применено sweeper-ом)
    # ignored  -> переход без эффекта (заказ уже в более позднем/терминальном состоянии)
    result: str