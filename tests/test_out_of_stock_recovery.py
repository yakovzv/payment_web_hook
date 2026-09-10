"""Этап 6: если товар не может выдать ни один поставщик - заказ честно
доводится до терминала возвратом (деньги назад), без падения и без зависания.
По деньгам сходится (оплачено == возвращено), повтор восстановления идемпотентен.

(Заменяет прежний сценарий «out_of_stock -> восстановимо»: на этом этапе
невыдаваемая позиция трактуется как невозможность выдать и честно возвращается.)"""

from conftest import (STORE, create_order, deliveries_count, order_money,
                      send_webhook, set_supplier, wait_for)


async def test_all_suppliers_fail_then_refund(http, db):
    await set_supplier(http, "A", mode="always_oos")
    await set_supplier(http, "B", mode="always_oos")

    order = await create_order(http, sku="KEY-EFT")
    await send_webhook(http, order["id"])

    final = await wait_for(http, order["id"], {"refunded"}, timeout=30.0)
    assert final["status"] == "refunded"             # терминал достигнут, без краха
    assert await deliveries_count(db, order["id"]) == 0

    # Оплачено == возвращено; выдано == 0.
    paid, delivered, refunded = await order_money(db, order["id"])
    assert paid == refunded == order["amount"]
    assert delivered == 0

    # Восстановление идемпотентно: терминальный возврат не откатывается и не дублируется.
    async with http.post(f"{STORE}/admin/recover") as r:
        assert r.status == 200
    again = await wait_for(http, order["id"], {"refunded"}, timeout=10.0)
    assert again["status"] == "refunded"
    assert await deliveries_count(db, order["id"]) == 0

    async with http.get(f"{STORE}/admin/reconcile") as r:
        report = await r.json()
    assert report["ledger"]["balanced"] is True
    assert report["money_mismatch"] == []
