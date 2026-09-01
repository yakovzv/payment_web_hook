"""Модель для хранения экземпляра ``APIRouter``."""

from dataclasses import dataclass
from typing import Tuple

from fastapi import APIRouter, FastAPI

__all__ = ["Routes"]


@dataclass(frozen=True)
class Routes:
    routers: Tuple[APIRouter, ...]

    def register_routes(self, app: FastAPI):
        for router in self.routers:
            app.include_router(router)
