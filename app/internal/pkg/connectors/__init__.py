import os

from app.internal.pkg.connectors.postgresql import Postgresql
from app.pkg.settings import settings


__all__ = ["Postgresql", "db_instance"]


def _env(name: str, default):
    """Переменные окружения приоритетнее settings.yml, чтобы Docker мог внедрять конфигурацию."""
    value = os.getenv(name)
    return value if value is not None else default


db_instance = Postgresql(
    username=_env("POSTGRES_LOGIN", settings.POSTGRES.login),
    password=_env("POSTGRES_PASSWORD", settings.POSTGRES.password),
    host=_env("POSTGRES_HOST", settings.POSTGRES.host),
    port=int(_env("POSTGRES_PORT", settings.POSTGRES.port)),
    database_name=_env("POSTGRES_DATABASE", settings.POSTGRES.database),
    min_size=settings.POSTGRES.pool_min_size,
    max_size=settings.POSTGRES.pool_max_size,
    timeout=settings.POSTGRES.pool_timeout,
)