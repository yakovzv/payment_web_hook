from contextlib import asynccontextmanager

from app.internal.pkg.connectors import db_instance
from app.internal.repository.repository import Repository

__all__ = ["DiscrepancyRepo"]


@asynccontextmanager
async def _conn(conn):
    if conn is not None:
        yield conn
    else:
        async with db_instance.get_connect() as c:
            yield c


class DiscrepancyRepo(Repository):
    async def record(self, *, supplier, kind, request_id=None, item_id=None,
                     order_id=None, code=None, detail=None, conn=None) -> None:
        """Идемпотентно зафиксировать расхождение: уникальность по
        supplier/kind/request_id/code, поэтому повтор не плодит строк."""
        async with _conn(conn) as c:
            await c.execute(
                """
                INSERT INTO supplier_discrepancies
                    (supplier, kind, request_id, item_id, order_id, code, detail)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (supplier, kind, COALESCE(request_id,''), COALESCE(code,''))
                DO NOTHING
                """,
                supplier, kind, request_id, item_id, order_id, code, detail,
            )

    async def resolve(self, *, supplier, kind, request_id=None, code=None, conn=None) -> None:
        async with _conn(conn) as c:
            await c.execute(
                """
                UPDATE supplier_discrepancies
                SET status='resolved', resolved_at=now()
                WHERE supplier=$1 AND kind=$2
                  AND COALESCE(request_id,'')=COALESCE($3,'')
                  AND COALESCE(code,'')=COALESCE($4,'')
                  AND status='open'
                """,
                supplier, kind, request_id, code,
            )

    async def list_open(self):
        async with db_instance.get_connect() as conn:
            return await conn.fetch(
                """
                SELECT supplier, kind, request_id, item_id, order_id, code, detail, created_at
                FROM supplier_discrepancies
                WHERE status='open'
                ORDER BY created_at
                """
            )

    async def count_open(self) -> int:
        async with db_instance.get_connect() as conn:
            return await conn.fetchval(
                "SELECT count(*) FROM supplier_discrepancies WHERE status='open'"
            )
