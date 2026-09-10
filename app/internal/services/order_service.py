import uuid

from app.internal.pkg.exceptions import OrderNotFound, ProductInactive, ProductNotFound
from app.internal.pkg.models.order import Order, OrderView
from app.internal.repository.postgresql.catalog import CatalogRepo
from app.internal.repository.postgresql.event import EventRepo
from app.internal.repository.postgresql.order_items import OrderItemRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.internal.repository.postgresql.uow import transaction
from app.pkg.logger.events import log_event

__all__ = ["OrderService"]


class OrderService:
    def __init__(self, order_repo: OrderRepo, item_repo: OrderItemRepo,
                 catalog_repo: CatalogRepo, event_repo: EventRepo):
        self.order_repo = order_repo
        self.item_repo = item_repo
        self.catalog_repo = catalog_repo
        self.event_repo = event_repo

    @staticmethod
    def _new_order_id() -> str:
        return f"ord_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _new_item_id() -> str:
        return f"itm_{uuid.uuid4().hex[:16]}"

    async def create_order(self, skus: list[str]) -> Order:
        # Цена каждой строки фиксируется по каталогу на момент создания заказа.
        items = []
        for sku in skus:
            product = await self.catalog_repo.get_product(sku)
            if product is None:
                raise ProductNotFound
            if not product.is_active:
                raise ProductInactive
            items.append({
                "id": self._new_item_id(),
                "sku": product.sku,
                "amount": product.price,
                "currency": product.currency,
            })

        order_id = self._new_order_id()
        amount = sum(it["amount"] for it in items)
        currency = items[0]["currency"]
        # 1-строчный заказ хранит sku наверху (совместимость с этапом 1),
        # мультитоварный - NULL (истина в order_items).
        header_sku = items[0]["sku"] if len(items) == 1 else None

        async with transaction() as conn:
            row = await self.order_repo.create_header(
                conn, order_id=order_id, sku=header_sku, amount=amount, currency=currency,
            )
            await self.item_repo.create_many(conn, order_id, items)
            # История: неизменяемые события создания (заказ + каждая строка).
            await self.event_repo.append(
                conn, order_id=order_id, type="order_created",
                payload={"amount": amount, "currency": currency,
                         "items": [it["sku"] for it in items]},
            )
            for it in items:
                await self.event_repo.append(
                    conn, order_id=order_id, item_id=it["id"], type="item_created",
                    payload={"sku": it["sku"], "amount": it["amount"],
                             "currency": it["currency"]},
                )

        order = Order(**dict(row))
        log_event(
            "Заказ создан",
            order_id=order.id,
            items=[it["sku"] for it in items],
            amount=order.amount,
            currency=order.currency,
        )
        return order

    async def get_order(self, order_id: str) -> OrderView:
        order = await self.order_repo.get(order_id)
        if order is None:
            raise OrderNotFound
        return order