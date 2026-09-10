from datetime import datetime

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.internal.pkg.models.history import (LedgerAtView, OrderAtView,
                                             PeriodReport)
from app.internal.pkg.models.reconcile import (IntegrityReport, QueueProgress,
                                               ReconcileReport)
from app.internal.services import Services
from app.internal.services.history_service import HistoryService
from app.internal.services.integrity_service import IntegrityService
from app.internal.services.payment_service import PaymentService
from app.internal.services.reconcile_service import ReconcileService

router = APIRouter(tags=["admin"], prefix="/admin")


class RateLimitIn(BaseModel):
    limit_per_window: int
    window_seconds: int = 60


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


@router.get(
    "/integrity",
    status_code=status.HTTP_200_OK,
    description="Открытые расхождения с поставщиком (недоверенный поставщик)",
)
@inject
async def integrity(
    integrity_service: IntegrityService = Depends(Provide[Services.integrity_service]),
) -> dict:
    open_items = await integrity_service.open_discrepancies()
    return {"open": open_items, "count": len(open_items)}


@router.post(
    "/integrity/audit",
    status_code=status.HTTP_200_OK,
    description="Принудительно прогнать автосверку с поставщиком (идемпотентно)",
)
@inject
async def integrity_audit(
    integrity_service: IntegrityService = Depends(Provide[Services.integrity_service]),
) -> IntegrityReport:
    return await integrity_service.audit()


@router.get(
    "/queue",
    status_code=status.HTTP_200_OK,
    description="Прогресс: сколько в очереди / выдано / возвращено + лимиты поставщиков",
)
@inject
async def queue(
    reconcile_service: ReconcileService = Depends(Provide[Services.reconcile_service]),
) -> QueueProgress:
    return await reconcile_service.queue_progress()


@router.post(
    "/rate-limit/{supplier}",
    status_code=status.HTTP_200_OK,
    description="Задать лимит поставщика (запросов в окне) и сбросить окно",
)
@inject
async def set_rate_limit(
    supplier: str,
    body: RateLimitIn,
    reconcile_service: ReconcileService = Depends(Provide[Services.reconcile_service]),
) -> dict:
    await reconcile_service.set_rate_limit(supplier.upper(), body.limit_per_window, body.window_seconds)
    return {"ok": True, "supplier": supplier.upper(),
            "limit_per_window": body.limit_per_window, "window_seconds": body.window_seconds}


@router.get(
    "/orders/{order_id}/at",
    status_code=status.HTTP_200_OK,
    description="Состояние заказа на прошлый момент ts (реконструкция из истории)",
)
@inject
async def order_at(
    order_id: str,
    ts: datetime,
    history_service: HistoryService = Depends(Provide[Services.history_service]),
) -> OrderAtView:
    return await history_service.order_at(order_id, ts)


@router.get(
    "/ledger/at",
    status_code=status.HTTP_200_OK,
    description="Остатки по счетам на прошлый момент ts",
)
@inject
async def ledger_at(
    ts: datetime,
    history_service: HistoryService = Depends(Provide[Services.history_service]),
) -> LedgerAtView:
    return await history_service.ledger_at(ts)


@router.get(
    "/report",
    status_code=status.HTTP_200_OK,
    description="Итоги за период [from_ts, to_ts] из истории (сходятся с остатками)",
)
@inject
async def period_report(
    from_ts: datetime,
    to_ts: datetime,
    history_service: HistoryService = Depends(Provide[Services.history_service]),
) -> PeriodReport:
    return await history_service.period_report(from_ts, to_ts)