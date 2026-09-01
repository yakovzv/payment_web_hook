"""Фоновый воркер: разбирает очередь выдачи. Воркеров может быть несколько —
заказы делятся через SKIP LOCKED, без двойной выдачи."""

import asyncio

from app.internal.pkg.config import config
from app.internal.services.delivery_service import DeliveryService
from app.pkg.logger import get_logger


class DeliveryWorker:
    def __init__(self, delivery_service: DeliveryService, name: str = "delivery-worker"):
        self.delivery_service = delivery_service
        self.name = name
        self.logger = get_logger(__name__)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name=self.name)
            self.logger.info("Воркер выдачи запущен [%s]", self.name)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.delivery_service.process_once()
            except Exception:
                self.logger.exception("Ошибка в итерации воркера выдачи")
                processed = 0
            if processed == 0:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=config.DELIVERY_POLL_INTERVAL_SEC
                    )
                except asyncio.TimeoutError:
                    pass