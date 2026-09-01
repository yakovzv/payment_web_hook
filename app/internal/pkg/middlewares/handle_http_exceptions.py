"""Ловит доменные BaseException и отдаёт их клиенту как JSON {"message": ...}."""

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.pkg.models.base.exception import BaseException


def handle_api_exceptions(request: Request, exc: BaseException):
    """Обрабатывает все внутренние исключения, унаследованные от `BaseException`."""
    _ = request

    return JSONResponse(status_code=exc.status_code, content={"message": exc.message})
