"""Фоновый воркер автосверки с недоверенным поставщиком: периодически прогоняет
IntegrityService.audit() - привязывает утёкшие коды и фиксирует расхождения.
Идемпотентно; несколько экземпляров безопасны."""

import asyncio

from app.internal.pkg.config import config
from app.internal.services.integrity_service import IntegrityService
from app.pkg.logger import get_logger


class IntegrityWorker:
    def __init__(self, integrity_service: IntegrityService, name: str = "integrity-worker"):
        self.integrity_service = integrity_service
        self.name = name
        self.logger = get_logger(__name__)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name=self.name)
            self.logger.info("Воркер автосверки запущен [%s]", self.name)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.integrity_service.audit()
            except Exception:
                self.logger.exception("Ошибка в итерации воркера автосверки")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=config.INTEGRITY_INTERVAL_SEC
                )
            except asyncio.TimeoutError:
                pass
