from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.internal.pkg.models.reconcile import ReconcileReport
from app.internal.services import Services
from app.internal.services.payment_service import PaymentService
from app.internal.services.reconcile_service import ReconcileService

router = APIRouter(tags=["admin"], prefix="/admin")


@router.get(
    "/reconcile",
    status_code=status.HTTP_200_OK,
    description="Аудит: оплачено-но-не-выдано / выдано-но-не-оплачено / баланс журнала",
)
@inject
async def reconcile(
    reconcile_service: ReconcileService = Depends(Provide[Services.reconcile_service]),
) -> ReconcileReport:
    return await reconcile_service.reconcile()


@router.post(
    "/recover",
    status_code=status.HTTP_200_OK,
    description="Повторная постановка застрявших/восстановимых заказов в очередь (безопасно, идемпотентно)",
)
@inject
async def recover(
    reconcile_service: ReconcileService = Depends(Provide[Services.reconcile_service]),
    payment_service: PaymentService = Depends(Provide[Services.payment_service]),
) -> dict:
    # Применяем все события вебхуков, пришедшие раньше, чем появился их заказ,
    # затем повторно ставим в очередь застрявшие/восстановимые выдачи.
    applied = await payment_service.apply_pending()
    count = await reconcile_service.recover()
    return {"applied_pending_events": applied, "requeued": count}