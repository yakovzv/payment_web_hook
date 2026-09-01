"""Логика заглушки-поставщика: идемпотентность по request_id и инъекция
отказов/таймаутов. SQL — в SupplierRepo."""

import asyncio
import random

from fastapi import HTTPException

from app.internal.pkg.models.delivery import IssueRequest, IssueResponse
from app.pkg.logger import get_logger
from supplier.repository import SupplierRepo

logger = get_logger("supplier")


class SupplierStub:
    def __init__(self, repo: SupplierRepo | None = None):
        self.repo = repo or SupplierRepo()

    async def issue(self, supplier: str, req: IssueRequest) -> IssueResponse:
        supplier = supplier.upper()

        # 1) Идемпотентность: тот же request_id ВСЕГДА возвращает тот же код, быстро
        #    и без инъекции отказов (код уже выдан).
        existing = await self.repo.find_issue(supplier, req.request_id)
        if existing:
            logger.info("Поставщик %s: повтор request_id=%s -> тот же код", supplier, req.request_id)
            return IssueResponse(status="ok", request_id=req.request_id, code=existing)

        cfg = await self.repo.get_config(supplier)
        mode = cfg["mode"]

        # 2) Жёсткие режимы отказа: код не выдаётся.
        if mode == "down":
            raise HTTPException(status_code=503, detail={"status": "error", "reason": "supplier_down"})
        if mode == "always_error":
            raise HTTPException(status_code=500, detail={"status": "error", "reason": "internal"})
        if mode == "always_oos":
            raise HTTPException(status_code=409, detail={"status": "error", "reason": "out_of_stock"})

        # 3) Случайный отказ/таймаут в режиме 'normal'.
        do_timeout = mode == "always_timeout"
        do_error = False
        if mode == "normal":
            r = random.random()
            if r < cfg["timeout_rate"]:
                do_timeout = True
            elif r < cfg["timeout_rate"] + cfg["error_rate"]:
                do_error = True

        if do_error:
            raise HTTPException(status_code=500, detail={"status": "error", "reason": "internal"})

        # 4) Выдаём код (коммит ДО искусственной задержки, поэтому таймаут реально
        #    означает «код выдан, но ответ потерян»).
        code = await self.repo.reserve_code(supplier, req.request_id, req.sku, req.order_id)
        if code is None:
            raise HTTPException(status_code=409, detail={"status": "error", "reason": "out_of_stock"})

        # 5) Ловушка таймаута: отвечаем медленнее клиентского таймаута. Код уже
        #    сохранён; клиент повторит с тем же request_id.
        if do_timeout:
            logger.info("Поставщик %s: ТАЙМАУТ после выдачи request_id=%s", supplier, req.request_id)
            await asyncio.sleep(cfg["timeout_delay_sec"])

        logger.info("Поставщик %s: выдан request_id=%s code=%s", supplier, req.request_id, code)
        return IssueResponse(status="ok", request_id=req.request_id, code=code)

    async def set_config(self, supplier: str, **fields) -> None:
        await self.repo.set_config(supplier.upper(), fields)

    async def status(self, supplier: str):
        supplier = supplier.upper()
        cfg = await self.repo.get_config(supplier)
        counts = await self.repo.counts(supplier)
        return supplier, cfg, counts

    async def reset(self, supplier: str, restock: bool = False) -> None:
        await self.repo.reset(supplier.upper(), restock)