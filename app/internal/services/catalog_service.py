from typing import List

from app.internal.pkg.models.catalog import Product, StorefrontItem
from app.internal.repository.postgresql.catalog import CatalogRepo

__all__ = ["CatalogService"]


class CatalogService:
    def __init__(self, catalog_repo: CatalogRepo):
        self.catalog_repo = catalog_repo

    async def storefront(self, page: int = 1, size: int = 50) -> List[StorefrontItem]:
        return await self.catalog_repo.storefront(page=page, size=size)

    async def get_product(self, sku: str) -> Product:
        return await self.catalog_repo.get_product(sku)