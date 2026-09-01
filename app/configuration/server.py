import asyncio
from contextlib import asynccontextmanager
from typing import TypeVar, AsyncGenerator, Optional, List, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.configuration import __containers__
from app.internal.pkg.middlewares.handle_http_exceptions import handle_api_exceptions
from app.internal.routes import __routes__
from app.pkg.models.base.exception import BaseException
from app.internal.services import Services
from .events import startup_events
from .events import shutdown_events


__all__ = ["Server"]

from ..internal.workers import Workers

FastAPIInstance = TypeVar("FastAPIInstance", bound="FastAPI")


class Server:
    def __init__(
            self,
            start_up_events: Optional[List[Callable]],
            shut_down_events: Optional[List[Callable]],
    ):
        self.start_up_events = start_up_events
        self.shut_down_events = shut_down_events
        self.app = FastAPI(
            lifespan=self.lifespan
        )
        self._register_routes(self.app)
        self._register_middlewares(self.app)
        self._register_http_exceptions(self.app)
        self._register_services(self.app)

    def get_app(self) -> FastAPIInstance:
        return self.app


    @staticmethod
    def _register_services(app: FastAPIInstance):
        services = Services()
        services.wire(
            packages=[
                "app.internal.routes",
                "app.configuration",
                "app.pkg.clients",
                "app.internal.services",
            ],
        )
        app.services = services

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncGenerator:
        __containers__.wire_packages(app=self.app)
        for callback in self.start_up_events:
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                await asyncio.to_thread(callback)
        yield
        for callback in self.shut_down_events:
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                await asyncio.to_thread(callback)

    @staticmethod
    def _register_routes(app: FastAPIInstance) -> None:
        __routes__.register_routes(app)

    @staticmethod
    def _register_http_exceptions(app: FastAPIInstance):
        app.add_exception_handler(BaseException, handle_api_exceptions)

    @staticmethod
    def __register_cors_origins(app: FastAPIInstance):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _register_middlewares(self, app):
        self.__register_cors_origins(app)
