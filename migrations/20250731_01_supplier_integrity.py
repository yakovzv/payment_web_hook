"""
недоверенный поставщик: ответу /issue доверять нельзя. Журнал расхождений с
поставщиком - их находит и по возможности чинит фоновый IntegrityWorker
(сверка нашей таблицы deliveries с аудит-выгрузкой issues поставщика).
Плюс режимы византийского поведения заглушки для воспроизводимых тестов.
"""

from yoyo import step

__depends__ = {"20250728_01_multi_item"}

schema = """
CREATE TABLE supplier_discrepancies (
    id          BIGSERIAL PRIMARY KEY,
    supplier    TEXT        NOT NULL,
    kind        TEXT        NOT NULL,   -- leaked_issue|duplicate_code|foreign_code|
                                        -- code_mismatch|phantom_delivery|refunded_but_issued
    request_id  TEXT,
    item_id     TEXT,
    order_id    TEXT,
    code        TEXT,
    detail      TEXT,
    status      TEXT        NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','resolved')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
-- Идемпотентная фиксация: один и тот же дефект не плодит строк.
CREATE UNIQUE INDEX supplier_discrepancies_uniq
    ON supplier_discrepancies (supplier, kind, COALESCE(request_id,''), COALESCE(code,''));
CREATE INDEX supplier_discrepancies_open_idx
    ON supplier_discrepancies (created_at) WHERE status = 'open';

-- Режимы византийского поведения заглушки-поставщика (для воспроизводимых тестов).
ALTER TABLE supplier_config DROP CONSTRAINT supplier_config_mode_check;
ALTER TABLE supplier_config ADD CONSTRAINT supplier_config_mode_check CHECK (mode IN
    ('normal','always_ok','always_timeout','always_error','always_oos','down',
     'duplicate_code','foreign_code','error_but_issue'));
"""

rollback = """
ALTER TABLE supplier_config DROP CONSTRAINT IF EXISTS supplier_config_mode_check;
ALTER TABLE supplier_config ADD CONSTRAINT supplier_config_mode_check CHECK (mode IN
    ('normal','always_ok','always_timeout','always_error','always_oos','down'));
DROP TABLE IF EXISTS supplier_discrepancies;
"""

steps = [step(schema, rollback)]
