from typing import Optional

from pydantic import BaseModel


class SupplierConfigIn(BaseModel):
    mode: Optional[str] = None            # normal|always_ok|always_timeout|always_error|always_oos|down
    error_rate: Optional[float] = None
    timeout_rate: Optional[float] = None
    timeout_delay_sec: Optional[float] = None


class SupplierStatus(BaseModel):
    supplier: str
    mode: str
    error_rate: float
    timeout_rate: float
    timeout_delay_sec: float
    available: int
    issued: int