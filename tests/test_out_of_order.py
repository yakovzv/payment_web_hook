"""Этап 2: вебхук раньше заказа (критерий 3) — принят, отложен и применён,
когда заказ появился."""

import uuid

from conftest import STORE, deliveries_count, get_order, send_webhook, wait_for


async def test_webhook_before_order(http, db):
    order_id = f"ord_ooo_{uuid.uuid4().hex[:12]}"

    # 1) Вебхук приходит первым — заказа ещё нет.
    status, ack = await send_webhook(http, order_id)
    assert status == 200
    assert ack["result"] == "pending"

    # 2) Order genuinely absent.
    code, _ = await get_order(http, order_id)
    assert code == 404

    # 3) Заказ создаётся позже (эмуляция другого пути создания).
    await db.execute(
        "INSERT INTO orders (id, sku, amount, currency, status) "
        "VALUES ($1, 'STEAM-TOPUP-500', 500, 'RUB', 'created')",
        order_id,
    )

    # 4) Восстановление применяет отложенное событие и запускает выдачу.
    async with http.post(f"{STORE}/admin/recover") as r:
        assert r.status == 200

    final = await wait_for(http, order_id, {"delivered"})
    assert final["status"] == "delivered"
    assert final["code"]
    assert await deliveries_count(db, order_id) == 1