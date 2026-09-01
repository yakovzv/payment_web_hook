from abc import ABC
from typing import List, TypeVar

from pydantic import BaseModel

__all__ = ["Repository", "BaseRepository"]


BaseRepository = TypeVar("BaseRepository", bound="Repository")


class Repository(ABC):
    """Базовый интерфейс репозитория."""

    async def create(self, cmd: BaseModel) -> BaseModel:
        raise NotImplementedError

    async def read(self, query: BaseModel) -> BaseModel:
        raise NotImplementedError

    async def read_all(self) -> List[BaseModel]:
        raise NotImplementedError

    async def update(self, cmd: BaseModel) -> BaseModel:
        raise NotImplementedError

    async def delete(self, cmd: BaseModel) -> BaseModel:
        raise NotImplementedError
