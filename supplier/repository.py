"""Доступ к БД для заглушек-поставщиков (весь SQL стороны поставщика)."""

from app.internal.pkg.connectors import db_instance

__all__ = ["SupplierRepo"]


class SupplierRepo:
    async def get_config(self, supplier: str):
        """Вернуть конфиг поставщика, создав дефолтный, если его нет."""
        async with db_instance.get_connect() as conn:
            cfg = await conn.fetchrow(
                "SELECT mode, error_rate, timeout_rate, timeout_delay_sec "
                "FROM supplier_config WHERE supplier=$1",
                supplier,
            )
            if cfg is None:
                await conn.execute(
                    "INSERT INTO supplier_config (supplier) VALUES ($1) "
                    "ON CONFLICT (supplier) DO NOTHING",
                    supplier,
                )
                cfg = await conn.fetchrow(
                    "SELECT mode, error_rate, timeout_rate, timeout_delay_sec "
                    "FROM supplier_config WHERE supplier=$1",
                    supplier,
                )
            return cfg

    async def find_issue(self, supplier: str, request_id: str):
        async with db_instance.get_connect() as conn:
            row = await conn.fetchrow(
                "SELECT code FROM supplier_issues WHERE supplier=$1 AND request_id=$2",
                supplier, request_id,
            )
            return row["code"] if row else None

    async def list_issues(self, supplier: str):
        """Аудит-выгрузка: всё, что поставщик считает выданным (source of truth
        для сверки, в отличие от ненадёжного ответа /issue)."""
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                "SELECT request_id, code, sku, order_id, created_at "
                "FROM supplier_issues WHERE supplier=$1 ORDER BY created_at, request_id",
                supplier,
            )

    async def any_existing_code(self, supplier: str, exclude_request_id: str):
        """Любой уже выданный код (кроме текущего request_id) - сырьё для
        византийских режимов «дубль» / «чужой код»."""
        async with db_instance.get_connect() as conn:
            row = await conn.fetchrow(
                "SELECT code FROM supplier_issues "
                "WHERE supplier=$1 AND request_id<>$2 "
                "ORDER BY created_at DESC LIMIT 1",
                supplier, exclude_request_id,
            )
            return row["code"] if row else None

    async def record_issue(self, supplier: str, request_id: str, sku, order_id, code) -> None:
        """Записать выдачу без списания инвентаря (тот же код уходит второй раз)."""
        async with db_instance.get_connect() as conn:
            await conn.execute(
                """
                INSERT INTO supplier_issues (supplier, request_id, sku, order_id, code)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (supplier, request_id) DO NOTHING
                """,
                supplier, request_id, sku, order_id, code,
            )

    async def reserve_code(self, supplier: str, request_id: str, sku, order_id):
        """Атомарно занять один свободный код и записать идемпотентную выдачу.
        Возвращает код или None, если кодов нет."""
        async with db_instance.get_connect() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, code FROM supplier_inventory
                    WHERE supplier=$1 AND status='available'
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    supplier,
                )
                if row is None:
                    return None
                await conn.execute(
                    "UPDATE supplier_inventory SET status='issued' WHERE id=$1", row["id"]
                )
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO supplier_issues (supplier, request_id, sku, order_id, code)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (supplier, request_id) DO NOTHING
                    RETURNING code
                    """,
                    supplier, request_id, sku, order_id, row["code"],
                )
                if inserted is None:
                    # Параллельный вызов с тем же request_id занял слот: освобождаем
                    # наш зарезервированный код и возвращаем уже выданный.
                    await conn.execute(
                        "UPDATE supplier_inventory SET status='available' WHERE id=$1", row["id"]
                    )
                    existing = await conn.fetchrow(
                        "SELECT code FROM supplier_issues WHERE supplier=$1 AND request_id=$2",
                        supplier, request_id,
                    )
                    return existing["code"]
                return row["code"]

    async def set_config(self, supplier: str, fields: dict):
        sets, values = [], []
        for i, (k, v) in enumerate((f for f in fields.items() if f[1] is not None), start=2):
            sets.append(f"{k}=${i}")
            values.append(v)
        async with db_instance.get_connect() as conn:
            await conn.execute(
                "INSERT INTO supplier_config (supplier) VALUES ($1) "
                "ON CONFLICT (supplier) DO NOTHING",
                supplier,
            )
            if sets:
                await conn.execute(
                    f"UPDATE supplier_config SET {', '.join(sets)} WHERE supplier=$1",
                    supplier, *values,
                )

    async def counts(self, supplier: str):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status='available') AS available,
                  COUNT(*) FILTER (WHERE status='issued')    AS issued
                FROM supplier_inventory WHERE supplier=$1
                """,
                supplier,
            )

    async def reset(self, supplier: str, restock: bool):
        async with db_instance.get_connect() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE supplier_config SET mode='normal', error_rate=0, "
                    "timeout_rate=0 WHERE supplier=$1",
                    supplier,
                )
                if restock:
                    await conn.execute(
                        "DELETE FROM supplier_issues WHERE supplier=$1", supplier
                    )
                    await conn.execute(
                        "UPDATE supplier_inventory SET status='available' WHERE supplier=$1",
                        supplier,
                    )