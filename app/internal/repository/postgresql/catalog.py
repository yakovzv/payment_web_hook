from typing import List

from app.internal.pkg.connectors import db_instance
from app.internal.pkg.models.catalog import Product, StorefrontItem
from app.internal.repository.handlers.collect_response import collect_response
from app.internal.repository.repository import Repository

__all__ = ["CatalogRepo"]


class CatalogRepo(Repository):
    @collect_response
    async def storefront(self, page: int = 1, size: int = 50) -> List[StorefrontItem]:
        """«Горячий» запрос витрины (Stage 5).

        Читает денормализованный счётчик по каждому SKU (stock.available) вместо
        подсчёта строк, поэтому стоимость не зависит от количества кодов.
        Частичный/покрывающий индекс по products оставляет запрос в рамках index range scan.
        """
        limit = size
        offset = (page - 1) * size
        async with db_instance.get_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT p.sku, p.name, p.type, p.price, p.currency, p.image,
                       COALESCE(s.available, 0) AS available
                FROM products p
                LEFT JOIN stock s ON s.sku = p.sku
                WHERE p.is_active
                ORDER BY p.type, p.sku
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            return rows

    @collect_response(nullable=True)
    async def get_product(self, sku: str) -> Product:
        async with db_instance.get_connect() as conn:
            row = await conn.fetchrow(
                "SELECT sku, name, type, price, currency, image, is_active "
                "FROM products WHERE sku = $1",
                sku,
            )
            return row