"""Этап 1: успешный жизненный цикл заказа + баланс денежного журнала."""

from conftest import STORE, create_order, deliveries_count, send_webhook, wait_for


async def test_order_lifecycle_and_delivery(http, db):
    order = await create_order(http, sku="STEAM-TOPUP-500")
    assert order["status"] == "created"
    assert order["amount"] == 500

    status, ack = await send_webhook(http, order["id"])
    assert status == 200
    assert ack["result"] == "applied"

    final = await wait_for(http, order["id"], {"delivered"})
    assert final["status"] == "delivered"
    assert final["code"]                       # был выдан настоящий код
    assert final["supplier"] in ("A", "B")
    assert await deliveries_count(db, order["id"]) == 1


async def test_ledger_balances(http):
    async with http.get(f"{STORE}/admin/reconcile") as r:
        report = await r.json()
    ledger = report["ledger"]
    assert ledger["balanced"] is True
    assert ledger["total_debit"] == ledger["total_credit"]
    # Выданный заказ никогда не бывает "выдан, но не оплачен".
    assert report["delivered_not_paid"] == []


async def test_payment_failed(http, db):
    order = await create_order(http, sku="SUB-SPOTIFY-1M")
    status, ack = await send_webhook(http, order["id"], status="failed")
    assert status == 200 and ack["result"] == "applied"
    async with http.get(f"{STORE}/orders/{order['id']}") as r:
        body = await r.json()
    assert body["status"] == "payment_failed"
    assert await deliveries_count(db, order["id"]) == 0