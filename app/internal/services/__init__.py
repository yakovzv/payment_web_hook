from dependency_injector import containers, providers

from app.internal.repository.postgresql import Repositories
from app.internal.services.catalog_service import CatalogService
from app.internal.services.delivery_service import DeliveryService
from app.internal.services.order_service import OrderService
from app.internal.services.payment_service import PaymentService
from app.internal.services.reconcile_service import ReconcileService
from app.pkg.clients import Clients


class Services(containers.DeclarativeContainer):
    repositories = providers.Container(Repositories)
    clients = providers.Container(Clients)

    catalog_service = providers.Factory(
        CatalogService,
        catalog_repo=repositories.catalog_repository,
    )
    order_service = providers.Factory(
        OrderService,
        order_repo=repositories.order_repository,
        catalog_repo=repositories.catalog_repository,
    )
    payment_service = providers.Factory(
        PaymentService,
        webhook_repo=repositories.webhook_repository,
        order_repo=repositories.order_repository,
        ledger_repo=repositories.ledger_repository,
        outbox_repo=repositories.outbox_repository,
    )
    delivery_service = providers.Factory(
        DeliveryService,
        supplier_client=clients.supplier_client,
        delivery_repo=repositories.delivery_repository,
        order_repo=repositories.order_repository,
        outbox_repo=repositories.outbox_repository,
        stock_repo=repositories.stock_repository,
    )
    reconcile_service = providers.Factory(
        ReconcileService,
        reconcile_repo=repositories.reconcile_repository,
        ledger_repo=repositories.ledger_repository,
    )