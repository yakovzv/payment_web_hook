from dependency_injector import containers, providers

from ..settings import settings

__all__ = ["Connectors"]




class Connectors(containers.DeclarativeContainer):
    pass

    # postgresql = providers.Singleton(
    #     Postgresql,
    #     username=settings.POSTGRES.login,
    #     password=settings.POSTGRES.password,
    #     host=settings.POSTGRES.host,
    #     port=settings.POSTGRES.port,
    #     database_name=settings.POSTGRES.database,
    #     min_size=settings.POSTGRES.pool_min_size,
    #     max_size=settings.POSTGRES.pool_max_size,
    #     timeout=settings.POSTGRES.pool_timeout,
    # )


