import asyncpg

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["DeliveryRepo"]

# Результат попытки привязать код к строке.
BOUND = "bound"                 # код был свободен, привязали
ALREADY_BOUND = "already_bound"  # у строки уже есть код (идемпотентный повтор)
CODE_CONFLICT = "code_conflict"  # код уже принадлежит другой строке: поставщик соврал


class DeliveryRepo(Repository):
    async def get(self, item_id: str):
        async with db_instance.get_connect() as conn:
            return await conn.fetchrow(
                "SELECT supplier, code FROM deliveries WHERE item_id=$1", item_id
            )

    async def owner_of_code(self, conn, supplier: str, code: str):
        """Строка, которой уже принадлежит (supplier, code), или None."""
        return await conn.fetchrow(
            "SELECT item_id, order_id FROM deliveries WHERE supplier=$1 AND code=$2",
            supplier, code,
        )

    async def bind(self, conn, *, item_id, order_id, sku, supplier, request_id, code) -> str:
        """Атомарно закрепить код за строкой. Возвращает:
          BOUND          - код был свободен и привязан к этой строке;
          ALREADY_BOUND  - у строки уже есть код (PK item_id), идемпотентный повтор;
          CODE_CONFLICT  - код уже принадлежит другой строке (UNIQUE(supplier,code)),
                           то есть поставщик прислал дубль/чужой код, доверять нельзя.
        """
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO deliveries (item_id, order_id, sku, supplier, request_id, code)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (item_id) DO NOTHING
                RETURNING item_id
                """,
                item_id, order_id, sku, supplier, request_id, code,
            )
        except asyncpg.UniqueViolationError:
            # Сработал UNIQUE(supplier, code): код закреплён за другой строкой.
            return CODE_CONFLICT
        return BOUND if row is not None else ALREADY_BOUND
