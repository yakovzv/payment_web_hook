from dependency_injector import containers, providers

from app.internal.repository.postgresql.catalog import CatalogRepo
from app.internal.repository.postgresql.deliveries import DeliveryRepo
from app.internal.repository.postgresql.discrepancy import DiscrepancyRepo
from app.internal.repository.postgresql.event import EventRepo
from app.internal.repository.postgresql.ledger import LedgerRepo
from app.internal.repository.postgresql.order_items import OrderItemRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.internal.repository.postgresql.outbox import OutboxRepo
from app.internal.repository.postgresql.rate_limit import RateLimitRepo
from app.internal.repository.postgresql.reconcile import ReconcileRepo
from app.internal.repository.postgresql.stock import StockRepo
from app.internal.repository.postgresql.webhook import WebhookRepo


class Repositories(containers.DeclarativeContainer):
    catalog_repository = providers.Factory(CatalogRepo)
    order_repository = providers.Factory(OrderRepo)
    order_item_repository = providers.Factory(OrderItemRepo)
    webhook_repository = providers.Factory(WebhookRepo)
    ledger_repository = providers.Factory(LedgerRepo)
    delivery_repository = providers.Factory(DeliveryRepo)
    outbox_repository = providers.Factory(OutboxRepo)
    stock_repository = providers.Factory(StockRepo)
    reconcile_repository = providers.Factory(ReconcileRepo)
    discrepancy_repository = providers.Factory(DiscrepancyRepo)
    rate_limit_repository = providers.Factory(RateLimitRepo)
    event_repository = providers.Factory(EventRepo)