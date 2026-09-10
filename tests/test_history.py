"""Этап 9 (история/темпоральность): по append-only логу восстанавливается точное
состояние заказа и денег на любой прошлый момент; история только дополняется;
итоги за период считаются из истории и сходятся."""

import asyncpg
import pytest

from conftest import STORE, create_order, send_webhook, wait_for


async def _now(db):
    return await db.fetchval("SELECT now()")


async def _order_at(http, oid, ts):
    async with http.get(f"{STORE}/admin/orders/{oid}/at", params={"ts": ts.isoformat()}) as r:
        return r.status, await r.json()


def _money(view):
    """{account: balance(credit-debit)} из представления."""
    return {a["account"]: a["balance"] for a in view["money"]}


async def test_point_in_time_reconstruction(http, db):
    t_before = await _now(db)

    order = await create_order(http, sku="STEAM-TOPUP-500")   # 500
    oid = order["id"]
    t_created = await _now(db)

    # До создания заказ не существовал.
    _, before = await _order_at(http, oid, t_before)
    assert before["exists"] is False
    assert before["status"] == "absent"

    # На момент после создания, но до оплаты: created, денег нет.
    _, created = await _order_at(http, oid, t_created)
    assert created["exists"] is True
    assert created["status"] == "created"
    assert created["items"][0]["status"] == "created"
    assert created["money"] == []

    # Оплачиваем и ждём выдачи.
    await send_webhook(http, oid)
    final = await wait_for(http, oid, {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    t_after = await _now(db)

    # На момент после выдачи: delivered, код есть, обязательство закрыто, выручка признана.
    _, after = await _order_at(http, oid, t_after)
    assert after["status"] == "delivered"
    assert after["items"][0]["status"] == "delivered"
    assert after["items"][0]["code"]
    money = _money(after)
    assert money.get("customer_funds", 0) == 0        # оплачено == выдано
    assert money.get("revenue", 0) == 500

    # История НЕ переписана задним числом: прошлый срез всё ещё 'created' без денег.
    _, created_again = await _order_at(http, oid, t_created)
    assert created_again["status"] == "created"
    assert created_again["money"] == []


async def test_history_is_append_only(http, db):
    # Заводим заказ, чтобы были и события, и проводки.
    order = await create_order(http, sku="STEAM-TOPUP-500")
    oid = order["id"]
    await send_webhook(http, oid)
    await wait_for(http, oid, {"delivered"}, timeout=30.0)

    # Правки/удаления истории запрещены триггером на уровне БД.
    with pytest.raises(asyncpg.PostgresError):
        await db.execute("UPDATE order_events SET type='hacked' WHERE order_id=$1", oid)
    with pytest.raises(asyncpg.PostgresError):
        await db.execute("DELETE FROM order_events WHERE order_id=$1", oid)
    with pytest.raises(asyncpg.PostgresError):
        await db.execute("UPDATE ledger_entries SET amount=0 WHERE order_id=$1", oid)
    with pytest.raises(asyncpg.PostgresError):
        await db.execute("DELETE FROM ledger_entries WHERE order_id=$1", oid)

    # Данные на месте (ничего не удалилось).
    assert await db.fetchval("SELECT count(*) FROM order_events WHERE order_id=$1", oid) > 0


async def test_period_totals_reconcile(http, db):
    from_ts = await _now(db)

    order = await create_order(http, sku="KEY-CS2-PRIME")     # 1290
    await send_webhook(http, order["id"])
    await wait_for(http, order["id"], {"delivered"}, timeout=30.0)

    to_ts = await _now(db)

    async with http.get(f"{STORE}/admin/report",
                        params={"from_ts": from_ts.isoformat(),
                                "to_ts": to_ts.isoformat()}) as r:
        assert r.status == 200
        report = await r.json()

    # Итоги из истории сходятся: двойная запись сбалансирована, а два независимых
    # пути (остатки as-of vs обороты за период) дают один ответ по каждому счёту.
    assert report["double_entry_balanced"] is True
    assert report["consistent"] is True
    # Поступления == признанная выручка + возвраты за период.
    assert report["payments"] == report["revenue"] + report["refunds"]
    assert report["payments"] == 1290
    assert report["revenue"] == 1290
    assert report["refunds"] == 0
