"""Этап 8 (лимит поставщика / бэкпрешер): при всплеске заказов лимит поставщика
не превышается, ничего не теряется (durable-очередь), оплаченные обслуживаются
раньше неоплаченных, прогресс виден."""

import asyncio

from conftest import (STORE, create_order, deliveries_count, queue_progress,
                      send_webhook, set_rate_limit, supplier_status)


async def _delivered_of(db, order_ids):
    return await db.fetchval(
        "SELECT count(*) FROM order_items WHERE order_id = ANY($1::text[]) "
        "AND status='delivered'",
        order_ids,
    )


async def _queued_of(db, order_ids):
    return await db.fetchval(
        "SELECT count(*) FROM delivery_outbox b JOIN order_items i ON i.id=b.item_id "
        "WHERE i.order_id = ANY($1::text[]) AND b.status <> 'done'",
        order_ids,
    )


async def _poll(fn, target, timeout=20.0):
    import time
    deadline = time.monotonic() + timeout
    val = await fn()
    while val != target and time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        val = await fn()
    return val


async def test_limit_not_exceeded_and_nothing_lost(http, db):
    # A отдаёт максимум 3 запроса за окно; B заблокирован (лимит 0) - изолируем A.
    await set_rate_limit(http, "A", 3, window_seconds=60)
    await set_rate_limit(http, "B", 0, window_seconds=60)

    orders = []
    for _ in range(6):
        o = await create_order(http, sku="STEAM-TOPUP-500")
        await send_webhook(http, o["id"])
        orders.append(o["id"])
    ids = orders

    # Устаканивается: ровно 3 выдано, остальные 3 ждут в очереди (не потеряны).
    delivered = await _poll(lambda: _delivered_of(db, ids), 3, timeout=20.0)
    assert delivered == 3
    await asyncio.sleep(1.5)                       # даём шанс «протечь» лишнему
    assert await _delivered_of(db, ids) == 3       # лимит НЕ превышен
    assert await _queued_of(db, ids) == 3          # остальные встали в очередь
    assert (await supplier_status(http, "A"))["issued"] == 3   # ровно 3 запроса к A

    prog = await queue_progress(http)
    assert prog["queued"] >= 3                      # прогресс виден
    rate_a = next(r for r in prog["rate_limits"] if r["supplier"] == "A")
    assert rate_a["used"] <= rate_a["limit_per_window"] == 3

    # Поднимаем лимит -> очередь дренится, ничего не потеряно.
    await set_rate_limit(http, "A", 1000, window_seconds=60)
    delivered = await _poll(lambda: _delivered_of(db, ids), 6, timeout=30.0)
    assert delivered == 6
    assert await _queued_of(db, ids) == 0


async def test_paid_served_before_unpaid(http, db):
    # Условие 3: ёмкости мало (A=3), но оплаченные проходят, а неоплаченные не
    # занимают лимит вовсе (в очередь выдачи не попадают).
    await set_rate_limit(http, "A", 3, window_seconds=60)
    await set_rate_limit(http, "B", 0, window_seconds=60)

    # Сначала создаём 3 НЕоплаченных (раньше по времени), затем 3 оплаченных.
    unpaid = [(await create_order(http, sku="STEAM-TOPUP-500"))["id"] for _ in range(3)]
    paid = []
    for _ in range(3):
        o = await create_order(http, sku="STEAM-TOPUP-500")
        await send_webhook(http, o["id"])
        paid.append(o["id"])

    # Все три оплаченных выданы, несмотря на то что неоплаченные создали раньше.
    delivered = await _poll(lambda: _delivered_of(db, paid), 3, timeout=20.0)
    assert delivered == 3

    # Неоплаченные не тронуты: не выданы и в очереди выдачи их нет.
    assert await _delivered_of(db, unpaid) == 0
    assert await _queued_of(db, unpaid) == 0
    for oid in unpaid:
        async with http.get(f"{STORE}/orders/{oid}") as r:
            body = await r.json()
        assert body["status"] == "created"
        assert await deliveries_count(db, oid) == 0

    prog = await queue_progress(http)
    assert prog["unpaid_orders"] >= 3


async def test_queue_progress_shape(http):
    prog = await queue_progress(http)
    for key in ("queued", "delivered", "refunded", "unpaid_orders", "rate_limits"):
        assert key in prog
    suppliers = {r["supplier"] for r in prog["rate_limits"]}
    assert {"A", "B"} <= suppliers
