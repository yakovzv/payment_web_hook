#!/usr/bin/env python
"""Эмулятор платёжной системы и харнесс для проверки гонок.

Тот же скрипт шлёт вебхук оплаты и гоняет конкурентные проверки. Реального
эквайринга нет.

Примеры:
    python scripts/emulate_payment.py order --sku STEAM-TOPUP-500
    python scripts/emulate_payment.py pay --order ord_xxx
    python scripts/emulate_payment.py race --order ord_xxx --count 50
    python scripts/emulate_payment.py race --order ord_xxx --count 50 --same-event
    python scripts/emulate_payment.py demo --sku STEAM-TOPUP-500 --count 50
"""

import argparse
import asyncio
import uuid

import aiohttp

BASE = "http://localhost:8001"


async def create_order(session, base, sku):
    async with session.post(f"{base}/orders", json={"sku": sku}) as r:
        r.raise_for_status()
        return await r.json()


async def get_order(session, base, order_id):
    async with session.get(f"{base}/orders/{order_id}") as r:
        r.raise_for_status()
        return await r.json()


async def send_webhook(session, base, order_id, event_id=None, status="paid", amount=None):
    payload = {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:10]}",
        "order_id": order_id,
        "status": status,
        "amount": amount,
        "currency": "RUB",
        "created_at": "2025-01-01T12:00:00Z",
    }
    async with session.post(f"{base}/webhook/payment", json=payload) as r:
        body = await r.json()
        return r.status, body


async def race(session, base, order_id, count, same_event):
    shared = f"evt_{uuid.uuid4().hex[:10]}" if same_event else None
    tasks = [
        send_webhook(session, base, order_id, event_id=shared)
        for _ in range(count)
    ]
    results = await asyncio.gather(*tasks)
    summary = {}
    for status, body in results:
        key = f"{status}:{body.get('result')}"
        summary[key] = summary.get(key, 0) + 1
    return summary


async def wait_delivered(session, base, order_id, timeout=15.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        order = await get_order(session, base, order_id)
        if order["status"] in ("delivered", "partially_delivered", "refunded",
                                "payment_failed", "out_of_stock", "delivery_failed"):
            return order
        await asyncio.sleep(0.3)
    return await get_order(session, base, order_id)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("order"); p.add_argument("--sku", required=True)
    p = sub.add_parser("get"); p.add_argument("--order", required=True)
    p = sub.add_parser("pay")
    p.add_argument("--order", required=True); p.add_argument("--event", default=None)
    p.add_argument("--status", default="paid")
    p = sub.add_parser("race")
    p.add_argument("--order", required=True); p.add_argument("--count", type=int, default=50)
    p.add_argument("--same-event", action="store_true")
    p = sub.add_parser("demo")
    p.add_argument("--sku", default="STEAM-TOPUP-500"); p.add_argument("--count", type=int, default=50)
    p.add_argument("--same-event", action="store_true")

    args = parser.parse_args()
    async with aiohttp.ClientSession() as session:
        if args.cmd == "order":
            print(await create_order(session, args.base, args.sku))
        elif args.cmd == "get":
            print(await get_order(session, args.base, args.order))
        elif args.cmd == "pay":
            print(await send_webhook(session, args.base, args.order, args.event, args.status))
        elif args.cmd == "race":
            print("webhook responses:", await race(session, args.base, args.order, args.count, args.same_event))
            print("final order:", await wait_delivered(session, args.base, args.order))
        elif args.cmd == "demo":
            order = await create_order(session, args.base, args.sku)
            print("created:", order["id"], order["status"])
            summary = await race(session, args.base, order["id"], args.count, args.same_event)
            print(f"fired {args.count} parallel webhooks:", summary)
            final = await wait_delivered(session, args.base, order["id"])
            print("final order:", {k: final[k] for k in ("id", "status", "code", "supplier")})


if __name__ == "__main__":
    asyncio.run(main())