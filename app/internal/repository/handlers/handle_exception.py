from typing import Callable

from asyncpg import PostgresError, UniqueViolationError
from pydantic import BaseModel


from app.pkg.models.exceptions.repository import DriverError, UniqueViolation

__all__ = ["handle_exception"]


def handle_exception(func: Callable[..., BaseModel]):
    async def wrapper(*args: object, **kwargs: object) -> BaseModel:
        try:
            return await func(*args, **kwargs)
        except UniqueViolationError:
            raise UniqueViolation
        except PostgresError as e:
            raise DriverError(message=str(e))

    return wrapper
