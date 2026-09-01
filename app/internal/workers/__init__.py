from dependency_injector import containers, providers

from app.internal.repository import Repositories
from app.pkg.clients import Clients
from app.pkg.connectors import Connectors


class Workers(containers.DeclarativeContainer):
    repositories = providers.Container(Repositories.asyncpg)
    clients = providers.Container(Clients)
    connectors = providers.Container(Connectors)
