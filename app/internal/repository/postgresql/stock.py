from app.internal.repository.repository import Repository

__all__ = ["StockRepo"]


class StockRepo(Repository):
    async def decrement(self, conn, sku: str):
        await conn.execute(
            "UPDATE stock SET available = GREATEST(available - 1, 0), updated_at=now() "
            "WHERE sku=$1",
            sku,
        )