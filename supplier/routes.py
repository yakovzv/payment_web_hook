from fastapi import APIRouter, Query, status

from app.internal.pkg.models.delivery import IssueRequest, IssueResponse
from supplier.models import SupplierConfigIn, SupplierStatus
from supplier.service import SupplierStub

router = APIRouter()
_stub = SupplierStub()


@router.post("/{supplier}/issue", response_model=IssueResponse)
async def issue(supplier: str, req: IssueRequest) -> IssueResponse:
    return await _stub.issue(supplier, req)


@router.post("/{supplier}/config", status_code=status.HTTP_200_OK)
async def set_config(supplier: str, body: SupplierConfigIn) -> dict:
    await _stub.set_config(
        supplier,
        mode=body.mode,
        error_rate=body.error_rate,
        timeout_rate=body.timeout_rate,
        timeout_delay_sec=body.timeout_delay_sec,
    )
    return {"ok": True}


@router.get("/{supplier}/status", response_model=SupplierStatus)
async def get_status(supplier: str) -> SupplierStatus:
    name, cfg, counts = await _stub.status(supplier)
    return SupplierStatus(
        supplier=name,
        mode=cfg["mode"],
        error_rate=cfg["error_rate"],
        timeout_rate=cfg["timeout_rate"],
        timeout_delay_sec=cfg["timeout_delay_sec"],
        available=counts["available"],
        issued=counts["issued"],
    )


@router.post("/{supplier}/reset", status_code=status.HTTP_200_OK)
async def reset(supplier: str, restock: bool = Query(False)) -> dict:
    await _stub.reset(supplier, restock=restock)
    return {"ok": True}