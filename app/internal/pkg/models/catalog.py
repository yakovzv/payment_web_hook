from typing import Optional

from pydantic import BaseModel

__all__ = ["Product", "StorefrontItem"]


class Product(BaseModel):
    sku: str
    name: str
    type: str
    price: int
    currency: str
    image: Optional[str] = None
    is_active: bool = True


class StorefrontItem(BaseModel):
    """Одна строка "горячего" запроса витрины: товар + актуальный остаток."""

    sku: str
    name: str
    type: str
    price: int
    currency: str
    image: Optional[str] = None
    available: int