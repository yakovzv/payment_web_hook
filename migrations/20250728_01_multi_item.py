"""
мультитоварный заказ: несколько строк на заказ, каждая выдаётся своим
поставщиком. Гранулярность exactly-once переносится с заказа на строку
(deliveries и delivery_outbox ключуются по item_id). Деньги считаются на трёх
счетах (cash/customer_funds/revenue/refunds), инвариант «оплачено = выдано +
возвращено»: когда все строки терминальны, customer_funds заказа обнуляется.
deliveries/delivery_outbox рантаймовые (в сиде их нет) - пересоздаём с новым
ключом, сохраняя колонку order_id для отчётов.
"""

from yoyo import step

__depends__ = {"20250715_02_seed"}

schema = """
-- Строки заказа: у каждой свой SKU, своя цена и свой независимый жизненный цикл.
CREATE TABLE order_items (
    id         TEXT PRIMARY KEY,
    order_id   TEXT        NOT NULL REFERENCES orders(id),
    sku        TEXT        NOT NULL REFERENCES products(sku),
    amount     BIGINT      NOT NULL CHECK (amount >= 0),
    currency   TEXT        NOT NULL DEFAULT 'RUB',
    status     TEXT        NOT NULL DEFAULT 'created'
               CHECK (status IN ('created','paid','delivering','delivered','refunded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX order_items_order_idx  ON order_items (order_id);
-- Поиск невыданных строк для восстановления.
CREATE INDEX order_items_pending_idx ON order_items (order_id)
    WHERE status IN ('created','paid','delivering');

-- Заказ становится агрегатом: sku теперь опционален (заполняется для 1-строчных
-- заказов ради обратной совместимости), amount = сумма строк, а статус -
-- производный: delivered / partially_delivered / refunded.
ALTER TABLE orders ALTER COLUMN sku DROP NOT NULL;
ALTER TABLE orders DROP CONSTRAINT orders_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (status IN
    ('created','paid','delivering','delivered','partially_delivered','refunded',
     'payment_failed','out_of_stock','delivery_failed'));

-- deliveries: ключ переезжает с order_id на item_id (ровно одна выдача на строку).
DROP TABLE deliveries;
CREATE TABLE deliveries (
    item_id    TEXT PRIMARY KEY REFERENCES order_items(id),
    order_id   TEXT        NOT NULL REFERENCES orders(id),
    sku        TEXT        NOT NULL,
    supplier   TEXT        NOT NULL,
    request_id TEXT        NOT NULL,
    code       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Один и тот же код поставщика не может быть привязан к двум строкам.
CREATE UNIQUE INDEX deliveries_code_uniq ON deliveries (supplier, code);
CREATE INDEX deliveries_order_idx ON deliveries (order_id);

-- delivery_outbox: одна задача на строку, строки ретраятся независимо.
DROP TABLE delivery_outbox;
CREATE TABLE delivery_outbox (
    item_id         TEXT PRIMARY KEY REFERENCES order_items(id),
    order_id        TEXT        NOT NULL REFERENCES orders(id),
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
CREATE INDEX delivery_outbox_order_idx ON delivery_outbox (order_id);
"""

rollback = """
DROP TABLE IF EXISTS delivery_outbox;
DROP TABLE IF EXISTS deliveries;
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (status IN
    ('created','paid','delivering','delivered',
     'payment_failed','out_of_stock','delivery_failed'));
DROP TABLE IF EXISTS order_items;

CREATE TABLE deliveries (
    order_id     TEXT PRIMARY KEY REFERENCES orders(id),
    supplier     TEXT        NOT NULL,
    request_id   TEXT        NOT NULL,
    code         TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX deliveries_code_uniq ON deliveries (supplier, code);
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
"""

steps = [step(schema, rollback)]