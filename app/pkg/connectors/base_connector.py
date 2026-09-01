from abc import abstractmethod
from contextlib import asynccontextmanager

__all__ = ["BaseConnector"]


class BaseConnector:
    @abstractmethod
    def get_dsn(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    @asynccontextmanager
    async def get_connect(self):
        raise NotImplementedError()
