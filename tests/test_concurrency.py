"""Этап 2: «ровно один раз» (exactly-once) при конкурентных / дублирующихся вебхуках.

Критерии приёмки 1 и 2.
"""

import asyncio

from conftest import create_order, deliveries_count, send_webhook, wait_for


async def test_50_parallel_distinct_events_deliver_once(http, db):
    """50 конкурентных вебхуков 'paid' (с разными event_id) на один заказ ->
    ровно одна выдача, без потерь и дублирования."""
    order = await create_order(http, sku="STEAM-TOPUP-1000")

    results = await asyncio.gather(
        *[send_webhook(http, order["id"]) for _ in range(50)]
    )

    assert all(status == 200 for status, _ in results)          # быстрые ACK
    applied = [b for _, b in results if b["result"] == "applied"]
    ignored = [b for _, b in results if b["result"] == "ignored"]
    assert len(applied) == 1                                    # ровно один переход
    assert len(ignored) == 49                                   # остальные — no-op

    final = await wait_for(http, order["id"], {"delivered"})
    assert final["status"] == "delivered"
    assert final["code"]
    assert await deliveries_count(db, order["id"]) == 1          # <-- ровно одна выдача


async def test_50_duplicate_same_event_is_noop(http, db):
    """Один и тот же event_id, доставленный 50 раз, меняет состояние ровно один раз."""
    order = await create_order(http, sku="STEAM-TOPUP-2500")
    event_id = "evt_dup_fixed_001_" + order["id"]

    results = await asyncio.gather(
        *[send_webhook(http, order["id"], event_id=event_id) for _ in range(50)]
    )

    assert all(status == 200 for status, _ in results)
    applied = [b for _, b in results if b["result"] == "applied"]
    duplicate = [b for _, b in results if b["result"] == "duplicate"]
    assert len(applied) == 1
    assert len(duplicate) == 49

    final = await wait_for(http, order["id"], {"delivered"})
    assert final["status"] == "delivered"
    assert await deliveries_count(db, order["id"]) == 1