"""Этап 3: резервный переход (fallback) A -> B (критерий приёмки 5).

Поставщик A недоступен (окончательная ошибка). Выдача переключается на B, и
товар выдаётся ровно один раз — поставщиком B.
"""

from conftest import (create_order, deliveries_count, send_webhook,
                      set_supplier, supplier_status, wait_for)


async def test_fallback_to_b_when_a_unavailable(http, db):
    await set_supplier(http, "A", mode="always_error")   # A недоступен/выдаёт ошибки
    await set_supplier(http, "B", mode="normal")

    before_a = (await supplier_status(http, "A"))["issued"]
    before_b = (await supplier_status(http, "B"))["issued"]

    order = await create_order(http, sku="KEY-GTA5")
    await send_webhook(http, order["id"])

    final = await wait_for(http, order["id"], {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    assert final["supplier"] == "B"
    assert final["code"]
    assert await deliveries_count(db, order["id"]) == 1

    after_a = (await supplier_status(http, "A"))["issued"]
    after_b = (await supplier_status(http, "B"))["issued"]
    assert after_a == before_a               # A ничего не выдал
    assert after_b == before_b + 1           # ровно один код от B