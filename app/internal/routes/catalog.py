from typing import List

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, status

from app.internal.pkg.exceptions import ProductNotFound
from app.internal.pkg.models.catalog import Product, StorefrontItem
from app.internal.services import Services
from app.internal.services.catalog_service import CatalogService

router = APIRouter(tags=["catalog"], prefix="/catalog")


@router.get("", status_code=status.HTTP_200_OK, description="Storefront with live stock")
@inject
async def storefront(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    catalog_service: CatalogService = Depends(Provide[Services.catalog_service]),
) -> List[StorefrontItem]:
    return await catalog_service.storefront(page=page, size=size)


@router.get("/{sku}", status_code=status.HTTP_200_OK)
@inject
async def get_product(
    sku: str,
    catalog_service: CatalogService = Depends(Provide[Services.catalog_service]),
) -> Product:
    product = await catalog_service.get_product(sku)
    if product is None:
        raise ProductNotFound
    return product