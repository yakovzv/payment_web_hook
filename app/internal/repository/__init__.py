from dependency_injector import containers, providers

from . import postgresql

__all__ = ["Repositories"]


class Repositories(containers.DeclarativeContainer):
    asyncpg = providers.Container(postgresql.Repositories)
