"""Этап 6 (мультитоварный заказ): несколько товаров в одном заказе, каждый от
своего поставщика; частичная выдача с честным возвратом за невыданное; деньги
сходятся; повторы не создают лишних выдач/возвратов."""

from conftest import (STORE, SUPPLIERS, create_multi_order, deliveries_count,
                      item_status_counts, order_money, send_webhook,
                      set_supplier, wait_for)

KEYS3 = ["KEY-CS2-PRIME", "KEY-GTA5", "KEY-EFT"]  # 1290 + 1990 + 3490


async def _reconcile(http):
    async with http.get(f"{STORE}/admin/reconcile") as r:
        return await r.json()


async def test_multi_item_all_delivered(http, db):
    # Критерий 1: несколько товаров в заказе, каждый выдаётся поставщиком.
    await set_supplier(http, "A", mode="normal")
    await set_supplier(http, "B", mode="normal")

    order = await create_multi_order(http, KEYS3)
    assert order["status"] == "created"
    assert order["amount"] == 1290 + 1990 + 3490
    assert order["sku"] is None                      # мультитоварный: истина в строках

    status, ack = await send_webhook(http, order["id"])
    assert status == 200 and ack["result"] == "applied"

    final = await wait_for(http, order["id"], {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    assert len(final["items"]) == 3
    assert all(it["code"] for it in final["items"])  # у каждой строки свой код
    assert await deliveries_count(db, order["id"]) == 3

    # Критерий 3: оплачено == выдано + возвращено.
    paid, delivered, refunded = await order_money(db, order["id"])
    assert paid == delivered + refunded == order["amount"]
    assert refunded == 0

    report = await _reconcile(http)
    assert report["ledger"]["balanced"] is True
    assert report["money_mismatch"] == []


async def test_partial_delivery_and_refund(http, db):
    # Критерий 2: часть выдать нельзя -> выданное остаётся, за невыданное возврат.
    # Детерминированно оставляем у A ровно один код, у B - ноль.
    await set_supplier(http, "A", mode="normal")
    await set_supplier(http, "B", mode="normal")
    await db.execute("UPDATE supplier_inventory SET status='issued' WHERE supplier='B'")
    await db.execute("UPDATE supplier_inventory SET status='issued' WHERE supplier='A'")
    await db.execute(
        "UPDATE supplier_inventory SET status='available' "
        "WHERE id=(SELECT id FROM supplier_inventory WHERE supplier='A' ORDER BY id LIMIT 1)"
    )
    try:
        order = await create_multi_order(http, ["KEY-CS2-PRIME", "KEY-GTA5"])  # 1290 + 1990
        await send_webhook(http, order["id"])

        final = await wait_for(http, order["id"], {"partially_delivered"}, timeout=30.0)
        assert final["status"] == "partially_delivered"

        counts = await item_status_counts(db, order["id"])
        assert counts.get("delivered") == 1          # ровно одна строка выдана
        assert counts.get("refunded") == 1           # ровно одна возвращена
        assert await deliveries_count(db, order["id"]) == 1

        # Критерий 3: по деньгам сходится при частичной выдаче.
        paid, delivered, refunded = await order_money(db, order["id"])
        assert paid == 1290 + 1990
        assert delivered + refunded == paid          # ничего не потеряно и не задвоено
        assert delivered > 0 and refunded > 0

        report = await _reconcile(http)
        assert report["ledger"]["balanced"] is True
        assert report["money_mismatch"] == []
    finally:
        # Восстанавливаем пул кодов для остальных тестов.
        async with http.post(f"{SUPPLIERS}/A/reset?restock=true"):
            pass
        async with http.post(f"{SUPPLIERS}/B/reset?restock=true"):
            pass


async def test_repeat_steps_no_extra_issue_or_refund(http, db):
    # Критерий 4: любой шаг можно повторить без лишних выдач/возвратов.
    await set_supplier(http, "A", mode="normal")
    await set_supplier(http, "B", mode="normal")

    order = await create_multi_order(http, ["KEY-CS2-PRIME", "KEY-GTA5"])

    # Один и тот же event_id несколько раз -> применяется единожды.
    ev = "evt_multi_repeat_1"
    _, a1 = await send_webhook(http, order["id"], event_id=ev)
    _, a2 = await send_webhook(http, order["id"], event_id=ev)
    assert a1["result"] == "applied"
    assert a2["result"] == "duplicate"
    # Другой event_id по уже оплаченному заказу -> no-op.
    _, a3 = await send_webhook(http, order["id"], event_id="evt_multi_repeat_2")
    assert a3["result"] == "ignored"

    final = await wait_for(http, order["id"], {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    assert await deliveries_count(db, order["id"]) == 2

    # Повторный ручной прогон выдачи не создаёт лишних выдач.
    async with http.post(f"{STORE}/orders/{order['id']}/redeliver") as r:
        assert r.status == 200
    async with http.post(f"{STORE}/admin/recover") as r:
        assert r.status == 200

    assert await deliveries_count(db, order["id"]) == 2
    paid, delivered, refunded = await order_money(db, order["id"])
    assert paid == delivered and refunded == 0       # деньги стабильны после повторов
    report = await _reconcile(http)
    assert report["ledger"]["balanced"] is True
    assert report["money_mismatch"] == []
