"""
история/темпоральность: по append-only логу восстанавливаем состояние заказа и
денег на любой прошлый момент. order_events - источник истины по переходам
состояний, ledger_entries - по деньгам (двойная запись, timestamped); изменяемые
orders/order_items - быстрая проекция «текущего». История только дополняется:
UPDATE/DELETE на order_events и ledger_entries запрещены триггером на уровне БД.
"""

from yoyo import step

__depends__ = {"20250805_01_rate_limit"}

schema = """
CREATE TABLE order_events (
    id          BIGSERIAL   PRIMARY KEY,           -- монотонный порядок
    order_id    TEXT        NOT NULL,
    item_id     TEXT,                              -- NULL для событий уровня заказа
    type        TEXT        NOT NULL,              -- order_created|item_created|payment_received|
                                                   -- payment_failed|item_delivered|item_refunded
    payload     JSONB       NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX order_events_order_idx ON order_events (order_id, occurred_at, id);
CREATE INDEX order_events_time_idx  ON order_events (occurred_at, id);

-- Append-only: правки/удаления истории запрещены на уровне БД.
CREATE FUNCTION reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only: % на % запрещён (историю нельзя переписать)',
        TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER order_events_immutable
    BEFORE UPDATE OR DELETE ON order_events
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE TRIGGER ledger_entries_immutable
    BEFORE UPDATE OR DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
"""

rollback = """
DROP TRIGGER IF EXISTS ledger_entries_immutable ON ledger_entries;
DROP TRIGGER IF EXISTS order_events_immutable ON order_events;
DROP FUNCTION IF EXISTS reject_mutation();
DROP TABLE IF EXISTS order_events;
"""

steps = [step(schema, rollback)]
