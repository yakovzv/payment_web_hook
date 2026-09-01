"""Настройки выдачи и интеграций — читаются из переменных окружения."""

import os

__all__ = ["config"]


def _f(name: str, default: float) -> float:
    v = os.getenv(name)
    return float(v) if v is not None else default


def _i(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v is not None else default


def _s(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None else default


class _Config:
    # Базовые URL двух заглушек поставщиков. В docker-compose оба указывают на
    # один и тот же сервис, различающийся по префиксу пути (/A, /B).
    SUPPLIER_A_URL: str = _s("SUPPLIER_A_URL", "http://localhost:8002/A")
    SUPPLIER_B_URL: str = _s("SUPPLIER_B_URL", "http://localhost:8002/B")

    # Порядок, в котором опрашиваются поставщики (A основной, B резервный/fallback).
    SUPPLIER_ORDER = ("A", "B")

    # HTTP-таймаут на один запрос при вызове /issue поставщика.
    SUPPLIER_TIMEOUT_SEC: float = _f("SUPPLIER_TIMEOUT_SEC", 2.0)

    # Повторы в рамках вызова при неоднозначном таймауте, прежде чем отложить в
    # фоновую очередь. Повторы переиспользуют ТОТ ЖЕ request_id, поэтому они могут
    # лишь забрать уже выданный код, но никогда не создадут второй.
    SUPPLIER_MAX_RETRIES: int = _i("SUPPLIER_MAX_RETRIES", 2)
    SUPPLIER_BACKOFF_BASE_SEC: float = _f("SUPPLIER_BACKOFF_BASE_SEC", 0.2)

    # Воркеры выдачи. Их может быть несколько — claim идёт через
    # FOR UPDATE SKIP LOCKED, поэтому два воркера никогда не берут один заказ.
    DELIVERY_WORKER_ENABLED: bool = _s("DELIVERY_WORKER_ENABLED", "1") == "1"
    DELIVERY_WORKER_COUNT: int = _i("DELIVERY_WORKER_COUNT", 2)
    DELIVERY_POLL_INTERVAL_SEC: float = _f("DELIVERY_POLL_INTERVAL_SEC", 0.5)
    DELIVERY_BATCH_SIZE: int = _i("DELIVERY_BATCH_SIZE", 5)
    # Верхняя граница экспоненциальной задержки между неудачными попытками доставки.
    DELIVERY_MAX_BACKOFF_SEC: float = _f("DELIVERY_MAX_BACKOFF_SEC", 30.0)

    # Воркеры восстановления / сверки (всё идемпотентно, обычно достаточно 1).
    RECOVERY_WORKER_ENABLED: bool = _s("RECOVERY_WORKER_ENABLED", "1") == "1"
    RECOVERY_WORKER_COUNT: int = _i("RECOVERY_WORKER_COUNT", 1)
    RECOVERY_INTERVAL_SEC: float = _f("RECOVERY_INTERVAL_SEC", 10.0)
    # Строка delivery_outbox в статусе 'processing' дольше этого времени считается
    # зависшей (воркер упал на полпути) и возвращается в обработку.
    STUCK_PROCESSING_SEC: float = _f("STUCK_PROCESSING_SEC", 60.0)


config = _Config()