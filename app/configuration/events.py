"""Старт и остановка фоновых воркеров, закрытие пула БД. Число воркеров — из .env."""

import asyncio

from app.internal.pkg.config import config
from app.internal.pkg.connectors import db_instance
from app.internal.services import Services
from app.internal.workers.delivery_worker import DeliveryWorker
from app.internal.workers.recovery_worker import RecoveryWorker

# Получаем экземпляры сервисов из DI-контейнера (все репозитории/клиенты связаны).
# Сервисы stateless, поэтому один набор можно безопасно делить между всеми воркерами.
_services = Services()
_delivery_service = _services.delivery_service()
_payment_service = _services.payment_service()
_reconcile_service = _services.reconcile_service()


def _delivery_count() -> int:
    return config.DELIVERY_WORKER_COUNT if config.DELIVERY_WORKER_ENABLED else 0


def _recovery_count() -> int:
    return config.RECOVERY_WORKER_COUNT if config.RECOVERY_WORKER_ENABLED else 0


_delivery_workers = [
    DeliveryWorker(_delivery_service, name=f"delivery-worker-{i + 1}")
    for i in range(_delivery_count())
]
_recovery_workers = [
    RecoveryWorker(_delivery_service, _payment_service, _reconcile_service,
                   name=f"recovery-worker-{i + 1}")
    for i in range(_recovery_count())
]


async def start_workers():
    for worker in (*_delivery_workers, *_recovery_workers):
        worker.start()


async def stop_workers():
    # Останавливаем все воркеры параллельно.
    await asyncio.gather(*(w.stop() for w in (*_delivery_workers, *_recovery_workers)))


async def close_pool():
    if db_instance.pool is not None:
        await db_instance.pool.close()


startup_events = [start_workers]
shutdown_events = [stop_workers, close_pool]