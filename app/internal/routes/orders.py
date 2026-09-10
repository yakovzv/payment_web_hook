from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, status

from app.internal.pkg.models.delivery import DeliveryResult
from app.internal.pkg.models.order import CreateOrderRequest, Order, OrderView
from app.internal.services import Services
from app.internal.services.delivery_service import DeliveryService
from app.internal.services.order_service import OrderService

router = APIRouter(tags=["orders"], prefix="/orders")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    description="Create an order by a single `sku` or a list of `items` (SKUs)",
)
@inject
async def create_order(
    body: CreateOrderRequest,
    order_service: OrderService = Depends(Provide[Services.order_service]),
) -> Order:
    return await order_service.create_order(body.skus())


@router.get("/{order_id}", status_code=status.HTTP_200_OK, description="Get order (with code)")
@inject
async def get_order(
    order_id: str,
    order_service: OrderService = Depends(Provide[Services.order_service]),
) -> OrderView:
    return await order_service.get_order(order_id)


@router.post(
    "/{order_id}/redeliver",
    status_code=status.HTTP_200_OK,
    description="Manually (re)trigger delivery for a recoverable order",
)
@inject
async def redeliver(
    order_id: str,
    delivery_service: DeliveryService = Depends(Provide[Services.delivery_service]),
) -> DeliveryResult:
    return await delivery_service.redeliver_order(order_id)