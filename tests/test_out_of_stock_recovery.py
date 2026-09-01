"""Этап 4: пустой остаток восстановим (критерий 6) — заказ висит в восстановимом
статусе, после пополнения доводится до выдачи."""

from conftest import (create_order, deliveries_count, send_webhook,
                      set_supplier, wait_for, STORE)


async def test_out_of_stock_then_recover(http, db):
    await set_supplier(http, "A", mode="always_oos")
    await set_supplier(http, "B", mode="always_oos")

    order = await create_order(http, sku="KEY-EFT")
    await send_webhook(http, order["id"])

    stuck = await wait_for(http, order["id"], {"out_of_stock", "delivery_failed"}, timeout=30.0)
    assert stuck["status"] in ("out_of_stock", "delivery_failed")   # recoverable, no crash
    assert await deliveries_count(db, order["id"]) == 0

    # Возвращаем поставщика и даём восстановлению довести заказ.
    await set_supplier(http, "A", mode="normal")
    async with http.post(f"{STORE}/admin/recover") as r:
        assert r.status == 200

    final = await wait_for(http, order["id"], {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    assert final["code"]
    assert await deliveries_count(db, order["id"]) == 1