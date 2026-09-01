"""Фоновый свипер: доводит зависшие заказы и применяет отложенные вебхуки.
Всё идемпотентно."""

import asyncio

from app.internal.pkg.config import config
from app.internal.services.delivery_service import DeliveryService
from app.internal.services.payment_service import PaymentService
from app.internal.services.reconcile_service import ReconcileService
from app.pkg.logger import get_logger


class RecoveryWorker:
    def __init__(
        self,
        delivery_service: DeliveryService,
        payment_service: PaymentService,
        reconcile_service: ReconcileService,
        name: str = "recovery-worker",
    ):
        self.delivery_service = delivery_service
        self.payment_service = payment_service
        self.reconcile_service = reconcile_service
        self.name = name
        self.logger = get_logger(__name__)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name=self.name)
            self.logger.info("Воркер восстановления запущен [%s]", self.name)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.payment_service.apply_pending()
                await self.delivery_service.reclaim_stuck()
                await self.reconcile_service.recover()
            except Exception:
                self.logger.exception("Ошибка в итерации воркера восстановления")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=config.RECOVERY_INTERVAL_SEC
                )
            except asyncio.TimeoutError:
                pass