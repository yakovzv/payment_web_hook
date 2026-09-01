import uuid

from app.internal.pkg.exceptions import OrderNotFound, ProductInactive, ProductNotFound
from app.internal.pkg.models.order import Order, OrderView
from app.internal.repository.postgresql.catalog import CatalogRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.pkg.logger.events import log_event

__all__ = ["OrderService"]


class OrderService:
    def __init__(self, order_repo: OrderRepo, catalog_repo: CatalogRepo):
        self.order_repo = order_repo
        self.catalog_repo = catalog_repo

    @staticmethod
    def _new_order_id() -> str:
        return f"ord_{uuid.uuid4().hex[:16]}"

    async def create_order(self, sku: str) -> Order:
        product = await self.catalog_repo.get_product(sku)
        if product is None:
            raise ProductNotFound
        if not product.is_active:
            raise ProductInactive

        order_id = self._new_order_id()
        # Сумма фиксируется по цене из каталога на момент создания заказа.
        order = await self.order_repo.create(
            order_id=order_id,
            sku=product.sku,
            amount=product.price,
            currency=product.currency,
        )
        log_event(
            "Заказ создан",
            order_id=order.id,
            sku=order.sku,
            amount=order.amount,
            currency=order.currency,
        )
        return order

    async def get_order(self, order_id: str) -> OrderView:
        order = await self.order_repo.get(order_id)
        if order is None:
            raise OrderNotFound
        return order