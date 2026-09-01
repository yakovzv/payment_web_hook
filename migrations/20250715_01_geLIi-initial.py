"""
начальная схема: каталог, заказы, платежи/вебхуки, доставки, outbox, книга проводок,
и таблицы-заглушки поставщика (инвентарь + идемпотентный журнал выдач).
"""

from yoyo import step

__depends__ = {}

schema = """
-- Каталог товаров (SKU — естественный ключ).
CREATE TABLE products (
    sku        TEXT PRIMARY KEY,
    name       TEXT        NOT NULL,
    type       TEXT        NOT NULL,
    price      BIGINT      NOT NULL CHECK (price >= 0),
    currency   TEXT        NOT NULL DEFAULT 'RUB',
    image      TEXT,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Обслуживает витрину: фильтр is_active, сортировка по (type, sku), LIMIT N.
-- Postgres проходит этот индекс по порядку и останавливается после LIMIT строк -> без сортировки, без
-- полного сканирования, стоимость не зависит от размера каталога.
CREATE INDEX products_storefront_idx ON products (type, sku) WHERE is_active;

-- Denormalized, O(1) stock counter per SKU for the "hot" storefront query (Stage 5).
CREATE TABLE stock (
    sku        TEXT PRIMARY KEY REFERENCES products(sku),
    available  INTEGER     NOT NULL DEFAULT 0 CHECK (available >= 0),
    reserved   INTEGER     NOT NULL DEFAULT 0 CHECK (reserved  >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Жизненный цикл заказа: created -> paid -> delivering -> delivered
--                        created -> payment_failed
--                        paid/delivering -> out_of_stock | delivery_failed (восстановимо)
CREATE TABLE orders (
    id           TEXT PRIMARY KEY,
    sku          TEXT        NOT NULL REFERENCES products(sku),
    amount       BIGINT      NOT NULL,
    currency     TEXT        NOT NULL DEFAULT 'RUB',
    status       TEXT        NOT NULL DEFAULT 'created'
                 CHECK (status IN ('created','paid','delivering','delivered',
                                   'payment_failed','out_of_stock','delivery_failed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at      TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX orders_status_idx ON orders (status);
-- Поиск для восстановления: "оплачено, но не доставлено дольше X".
CREATE INDEX orders_paid_undelivered_idx ON orders (paid_at)
    WHERE status IN ('paid','delivering','out_of_stock','delivery_failed');

-- Входящий ящик вебхуков (доставка "хотя бы один раз"). event_id — ключ идемпотентности от PSP.
CREATE TABLE webhook_events (
    event_id     TEXT PRIMARY KEY,
    order_id     TEXT        NOT NULL,
    status       TEXT        NOT NULL,
    amount       BIGINT,
    currency     TEXT,
    payload      JSONB       NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed    BOOLEAN     NOT NULL DEFAULT FALSE,
    processed_at TIMESTAMPTZ
);
-- Сборщик подхватывает события, которые ещё не удалось применить (доставка с нарушением порядка).
CREATE INDEX webhook_events_pending_idx ON webhook_events (received_at) WHERE processed = FALSE;

-- Ровно один выданный код на заказ. UNIQUE PK — жёсткая гарантия exactly-once.
CREATE TABLE deliveries (
    order_id     TEXT PRIMARY KEY REFERENCES orders(id),
    supplier     TEXT        NOT NULL,
    request_id   TEXT        NOT NULL,
    code         TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Один и тот же код поставщика никогда не может быть привязан к двум заказам.
CREATE UNIQUE INDEX deliveries_code_uniq ON deliveries (supplier, code);

-- Очередь задач на основе БД для асинхронной, повторяемой, устойчивой к сбоям доставки.
CREATE TABLE delivery_outbox (
    order_id        TEXT PRIMARY KEY REFERENCES orders(id),
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','done')),
    attempts        INTEGER     NOT NULL DEFAULT 0,
    last_error      TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX delivery_outbox_claim_idx ON delivery_outbox (next_attempt_at)
    WHERE status IN ('pending','processing');

-- Журнал денежных проводок с двойной записью. sum(debit) всегда должна равняться sum(credit).
CREATE TABLE ledger_entries (
    id         BIGSERIAL PRIMARY KEY,
    order_id   TEXT        NOT NULL,
    event_id   TEXT        NOT NULL,
    account    TEXT        NOT NULL,
    direction  TEXT        NOT NULL CHECK (direction IN ('debit','credit')),
    amount     BIGINT      NOT NULL CHECK (amount >= 0),
    currency   TEXT        NOT NULL DEFAULT 'RUB',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Одна сбалансированная проводка на каждое платёжное событие (идемпотентная запись).
CREATE UNIQUE INDEX ledger_event_account_idx ON ledger_entries (event_id, account, direction);

-- --- заглушки поставщика (изолированные таблицы; в реальной системе это была бы отдельная БД) ---

CREATE TABLE supplier_inventory (
    id         BIGSERIAL PRIMARY KEY,
    supplier   TEXT        NOT NULL,
    code       TEXT        NOT NULL,
    status     TEXT        NOT NULL DEFAULT 'available'
               CHECK (status IN ('available','issued')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX supplier_inventory_code_uniq ON supplier_inventory (supplier, code);
CREATE INDEX supplier_inventory_avail_idx ON supplier_inventory (supplier)
    WHERE status = 'available';

-- Идемпотентность на стороне поставщика: один и тот же request_id ВСЕГДА возвращает один и тот же код.
CREATE TABLE supplier_issues (
    supplier   TEXT        NOT NULL,
    request_id TEXT        NOT NULL,
    sku        TEXT,
    order_id   TEXT,
    code       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (supplier, request_id)
);

-- Настраиваемая в рантайме инъекция сбоев для каждого поставщика (для воспроизводимых тестов).
CREATE TABLE supplier_config (
    supplier          TEXT PRIMARY KEY,
    mode              TEXT    NOT NULL DEFAULT 'normal'
                      CHECK (mode IN ('normal','always_ok','always_timeout',
                                      'always_error','always_oos','down')),
    error_rate        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    timeout_rate      DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    timeout_delay_sec DOUBLE PRECISION NOT NULL DEFAULT 10.0
);
"""

rollback = """
DROP TABLE IF EXISTS supplier_config;
DROP TABLE IF EXISTS supplier_issues;
DROP TABLE IF EXISTS supplier_inventory;
DROP TABLE IF EXISTS ledger_entries;
DROP TABLE IF EXISTS delivery_outbox;
DROP TABLE IF EXISTS deliveries;
DROP TABLE IF EXISTS webhook_events;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS stock;
DROP TABLE IF EXISTS products;
"""

steps = [step(schema, rollback)]