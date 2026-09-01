#!/usr/bin/env python
"""Этап 5: заливает тысячи SKU и печатает план «горячего» запроса витрины.

    python scripts/load_catalog.py --count 5000

Показывает EXPLAIN (ANALYZE, BUFFERS) — разбор см. в README, раздел про этап 5.
"""

import argparse
import asyncio
import os

import asyncpg

DSN = os.getenv(
    "LOAD_DSN",
    "postgresql://shop:shop@localhost:5432/shop",
)

TYPES = ["topup", "key", "subscription", "giftcard"]

STOREFRONT_SQL = """
SELECT p.sku, p.name, p.type, p.price, p.currency, p.image,
       COALESCE(s.available, 0) AS available
FROM products p
LEFT JOIN stock s ON s.sku = p.sku
WHERE p.is_active
ORDER BY p.type, p.sku
LIMIT 50 OFFSET 0
"""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--dsn", default=DSN)
    args = ap.parse_args()

    conn = await asyncpg.connect(args.dsn)
    try:
        # Пакетная вставка синтетических товаров + остатков.
        rows = []
        for i in range(args.count):
            sku = f"LOAD-{i:07d}"
            rows.append((sku, f"Load product {i}", TYPES[i % len(TYPES)],
                         100 + (i % 5000), "RUB", "assets/x.png"))
        await conn.executemany(
            "INSERT INTO products (sku,name,type,price,currency,image) "
            "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (sku) DO NOTHING",
            rows,
        )
        await conn.executemany(
            "INSERT INTO stock (sku, available) VALUES ($1,$2) "
            "ON CONFLICT (sku) DO NOTHING",
            [(r[0], (i % 50)) for i, r in enumerate(rows)],
        )
        await conn.execute("ANALYZE products"); await conn.execute("ANALYZE stock")

        total = await conn.fetchval("SELECT count(*) FROM products")
        print(f"products in catalog: {total}\n")

        plan = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + STOREFRONT_SQL)
        print("EXPLAIN (ANALYZE, BUFFERS) for the storefront query:\n")
        for line in plan:
            print(" ", line[0])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())