from dependency_injector import containers, providers

from app.internal.repository.postgresql.catalog import CatalogRepo
from app.internal.repository.postgresql.deliveries import DeliveryRepo
from app.internal.repository.postgresql.ledger import LedgerRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.internal.repository.postgresql.outbox import OutboxRepo
from app.internal.repository.postgresql.reconcile import ReconcileRepo
from app.internal.repository.postgresql.stock import StockRepo
from app.internal.repository.postgresql.webhook import WebhookRepo


class Repositories(containers.DeclarativeContainer):
    catalog_repository = providers.Factory(CatalogRepo)
    order_repository = providers.Factory(OrderRepo)
    webhook_repository = providers.Factory(WebhookRepo)
    ledger_repository = providers.Factory(LedgerRepo)
    delivery_repository = providers.Factory(DeliveryRepo)
    outbox_repository = providers.Factory(OutboxRepo)
    stock_repository = providers.Factory(StockRepo)
    reconcile_repository = providers.Factory(ReconcileRepo)