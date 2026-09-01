"""HTTP-исключения уровня домена."""

from fastapi import status

from app.pkg.models.base.exception import BaseException

__all__ = ["ProductNotFound", "OrderNotFound", "ProductInactive"]


class ProductNotFound(BaseException):
    message = "Product (sku) not found"
    status_code = status.HTTP_404_NOT_FOUND


class ProductInactive(BaseException):
    message = "Product is not available for sale"
    status_code = status.HTTP_409_CONFLICT


class OrderNotFound(BaseException):
    message = "Order not found"
    status_code = status.HTTP_404_NOT_FOUND