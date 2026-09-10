"""HTTP-клиент к заглушкам-поставщикам: делает /issue и классифицирует ответ
(ok / нет в наличии / ошибка / таймаут). Таймаут не равен отказу."""

import asyncio

import aiohttp

from app.internal.pkg.config import config
from app.internal.pkg.models.delivery import IssueResponse
from app.pkg.logger import get_logger

__all__ = ["SupplierClient"]


class SupplierClient:
    def __init__(self):
        self._logger = get_logger(__name__)
        self._urls = {
            "A": config.SUPPLIER_A_URL,
            "B": config.SUPPLIER_B_URL,
        }

    async def issue(self, supplier: str, request_id: str, sku: str, order_id: str):
        """Return (outcome, IssueResponse|None).

        outcome in {"ok", "out_of_stock", "error", "timeout"}.
        """
        url = f"{self._urls[supplier]}/issue"
        payload = {"request_id": request_id, "sku": sku, "order_id": order_id}
        timeout = aiohttp.ClientTimeout(total=config.SUPPLIER_TIMEOUT_SEC)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return "ok", IssueResponse(**data)
                    if resp.status == 409:
                        # «нет в наличии» заглушка сигналит кодом 409.
                        return "out_of_stock", None
                    # Любой другой 4xx/5xx: однозначно «код не выдан».
                    return "error", None
        except asyncio.TimeoutError:
            return "timeout", None
        except aiohttp.ClientError as exc:
            # Отказ соединения / DNS / reset: поставщик недоступен == ошибка.
            self._logger.warning("Поставщик %s недоступен: %s", supplier, exc)
            return "error", None

    async def get_issue(self, supplier: str, request_id: str):
        """Что поставщик реально выдал по request_id (аудит). Код или None."""
        url = f"{self._urls[supplier]}/issue/{request_id}"
        timeout = aiohttp.ClientTimeout(total=config.SUPPLIER_TIMEOUT_SEC)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("code")
                    return None
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return None

    async def list_issues(self, supplier: str):
        """Полная аудит-выгрузка выданных кодов поставщика (list[dict])."""
        url = f"{self._urls[supplier]}/issues"
        timeout = aiohttp.ClientTimeout(total=config.SUPPLIER_TIMEOUT_SEC)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return []
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return []