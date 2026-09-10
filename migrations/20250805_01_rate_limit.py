"""
лимит поставщика / бэкпрешер: перед каждым вызовом /issue берём токен из общего
(в БД, значит распределённого) счётчика фиксированного окна. Нет токена - задача
остаётся в durable-очереди delivery_outbox и повторится позже, так лимит не
превышается и ничего не теряется. В очередь выдачи попадают только оплаченные
строки (неоплаченные ёмкость не тратят), среди них - FIFO по времени постановки.
"""

from yoyo import step

__depends__ = {"20250731_01_supplier_integrity"}

schema = """
CREATE TABLE supplier_rate_limit (
    supplier         TEXT PRIMARY KEY,
    limit_per_window INT         NOT NULL DEFAULT 1000 CHECK (limit_per_window >= 0),
    window_seconds   INT         NOT NULL DEFAULT 60   CHECK (window_seconds > 0),
    window_start     TIMESTAMPTZ NOT NULL DEFAULT now(),
    used             INT         NOT NULL DEFAULT 0
);

-- Дефолт щедрый (обычные тесты не троттлятся); тесты лимита ставят низкий предел.
INSERT INTO supplier_rate_limit (supplier, limit_per_window, window_seconds)
VALUES ('A', 1000, 60), ('B', 1000, 60);
"""

rollback = """
DROP TABLE IF EXISTS supplier_rate_limit;
"""

steps = [step(schema, rollback)]
