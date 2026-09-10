"""Общие фикстуры. Тесты идут по живому стеку (docker compose up); если он
недоступен - весь набор пропускается."""

import os
import uuid

import aiohttp
import asyncpg
import pytest
import pytest_asyncio

STORE = os.getenv("STORE_URL", "http://localhost:8001")
SUPPLIERS = os.getenv("SUPPLIER_URL", "http://localhost:8002")
DSN = os.getenv("TEST_DSN", "postgresql://shop:shop@localhost:5432/shop")


@pytest_asyncio.fixture
async def http():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest_asyncio.fixture
async def db():
    conn = await asyncpg.connect(DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def _require_stack(http):
    try:
        async with http.get(f"{STORE}/catalog?size=1", timeout=aiohttp.ClientTimeout(total=3)) as r:
            r.raise_for_status()
    except Exception:
        pytest.skip("stack not reachable - run `docker compose up -d` first")


@pytest_asyncio.fixture(autouse=True)
async def reset_suppliers(http, _require_stack):
    """Чистое состояние поставщиков перед каждым тестом: mode=normal, восстановленный
    сток и очищенный журнал выдач (важно для византийских сценариев), плюс щедрый
    rate-limit (обычные тесты не троттлятся)."""
    for s in ("A", "B"):
        await http.post(f"{SUPPLIERS}/{s}/reset?restock=true")
        await http.post(f"{STORE}/admin/rate-limit/{s}",
                        json={"limit_per_window": 1000, "window_seconds": 60})
    yield


# --- вспомогательные функции -----------------------------------------------

async def create_order(http, sku="STEAM-TOPUP-500"):
    async with http.post(f"{STORE}/orders", json={"sku": sku}) as r:
        r.raise_for_status()
        return await r.json()


async def create_multi_order(http, skus):
    """Мультитоварный заказ: список SKU (по одной штуке на позицию)."""
    async with http.post(f"{STORE}/orders", json={"items": skus}) as r:
        r.raise_for_status()
        return await r.json()


async def get_order(http, order_id):
    async with http.get(f"{STORE}/orders/{order_id}") as r:
        return r.status, (await r.json())


async def send_webhook(http, order_id, event_id=None, status="paid", amount=None):
    payload = {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:10]}",
        "order_id": order_id,
        "status": status,
        "amount": amount,
        "currency": "RUB",
        "created_at": "2025-01-01T12:00:00Z",
    }
    async with http.post(f"{STORE}/webhook/payment", json=payload) as r:
        return r.status, (await r.json())


async def set_supplier(http, supplier, **cfg):
    async with http.post(f"{SUPPLIERS}/{supplier}/config", json=cfg) as r:
        r.raise_for_status()


async def supplier_status(http, supplier):
    async with http.get(f"{SUPPLIERS}/{supplier}/status") as r:
        r.raise_for_status()
        return await r.json()


async def wait_for(http, order_id, statuses, timeout=20.0):
    import asyncio
    import time
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        code, last = await get_order(http, order_id)
        if last.get("status") in statuses:
            return last
        await asyncio.sleep(0.25)
    return last


async def deliveries_count(db, order_id):
    return await db.fetchval("SELECT count(*) FROM deliveries WHERE order_id=$1", order_id)


async def set_rate_limit(http, supplier, limit_per_window, window_seconds=60):
    async with http.post(f"{STORE}/admin/rate-limit/{supplier}",
                         json={"limit_per_window": limit_per_window,
                               "window_seconds": window_seconds}) as r:
        r.raise_for_status()


async def queue_progress(http):
    async with http.get(f"{STORE}/admin/queue") as r:
        r.raise_for_status()
        return await r.json()


async def item_status_counts(db, order_id):
    """{'delivered': n, 'refunded': m, ...} по строкам заказа."""
    rows = await db.fetch(
        "SELECT status, count(*) AS c FROM order_items WHERE order_id=$1 GROUP BY status",
        order_id,
    )
    return {r["status"]: r["c"] for r in rows}


async def order_money(db, order_id):
    """(paid, delivered, refunded) в деньгах по журналу проводок заказа."""
    row = await db.fetchrow(
        """
        SELECT
          COALESCE(SUM(amount) FILTER (WHERE account='customer_funds' AND direction='credit'),0) AS paid,
          COALESCE(SUM(amount) FILTER (WHERE account='revenue' AND direction='credit'),0)        AS delivered,
          COALESCE(SUM(amount) FILTER (WHERE account='refunds' AND direction='credit'),0)        AS refunded
        FROM ledger_entries WHERE order_id=$1
        """,
        order_id,
    )
    return row["paid"], row["delivered"], row["refunded"]