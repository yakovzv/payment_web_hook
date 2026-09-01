"""Этап 3: ловушка таймаута (критерий 4) — A выдал и завис; повтор с тем же
request_id даёт тот же код, без второй выдачи."""

from conftest import (create_order, deliveries_count, send_webhook,
                      set_supplier, supplier_status, wait_for)


async def test_timeout_does_not_double_issue(http, db):
    # A: выдаёт и виснет. B: жёсткая ошибка — неверный fallback провалил бы тест.
    await set_supplier(http, "A", mode="always_timeout", timeout_delay_sec=8.0)
    await set_supplier(http, "B", mode="always_error")

    before_a = (await supplier_status(http, "A"))["issued"]
    before_b = (await supplier_status(http, "B"))["issued"]

    order = await create_order(http, sku="KEY-CS2-PRIME")
    await send_webhook(http, order["id"])

    final = await wait_for(http, order["id"], {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    assert final["supplier"] == "A"           # выдал A, а не резерв
    assert final["code"]
    assert await deliveries_count(db, order["id"]) == 1

    after_a = (await supplier_status(http, "A"))["issued"]
    after_b = (await supplier_status(http, "B"))["issued"]
    assert after_a == before_a + 1            # ровно ОДИН код списан у A
    assert after_b == before_b                # B never issued (no fallback on timeout)