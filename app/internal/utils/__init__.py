from dependency_injector import containers, providers

from app.internal.utils.connection_manager import ConnectionManager


class Utils(containers.DeclarativeContainer):
    connection_manager = providers.Singleton(ConnectionManager)
