from dependency_injector import containers, providers

from app.pkg.clients.supplier_client import SupplierClient

__all__ = ["Clients"]


class Clients(containers.DeclarativeContainer):
    supplier_client = providers.Singleton(SupplierClient)