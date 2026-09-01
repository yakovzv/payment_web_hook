from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.internal.pkg.models.payment import PaymentWebhook, WebhookAck
from app.internal.services import Services
from app.internal.services.payment_service import PaymentService

router = APIRouter(tags=["webhook"], prefix="/webhook")


@router.post(
    "/payment",
    status_code=status.HTTP_200_OK,
    description="Вебхук платёжной системы (at-least-once, идемпотентный, независимый от заказа)",
)
@inject
async def payment_webhook(
    body: PaymentWebhook,
    payment_service: PaymentService = Depends(Provide[Services.payment_service]),
) -> WebhookAck:
    # Всегда быстро подтверждаем ответом 200, чтобы PSP не повторял успешно
    # полученное событие. Любой временный сбой вызывает 5xx, и PSP доставит
    # событие повторно.
    return await payment_service.handle_webhook(body)