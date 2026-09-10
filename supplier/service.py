"""Логика заглушки-поставщика: идемпотентность по request_id и инъекция
отказов/таймаутов. SQL - в SupplierRepo."""

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

        # 1) Идемпотентность: тот же request_id всегда возвращает тот же код, быстро
        #    и без инъекции отказов (код уже выдан).
        existing = await self.repo.find_issue(supplier, req.request_id)
        if existing:
            logger.info("Поставщик %s: повтор request_id=%s, тот же код", supplier, req.request_id)
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

        # 2b) Византийские режимы: ответу /issue доверять нельзя.
        #     «дубль» / «чужой код» - молча отдаём уже выданный кому-то код
        #     (инвентарь не списываем), записывая ещё одну выдачу под этим request_id.
        if mode in ("duplicate_code", "foreign_code"):
            reuse = await self.repo.any_existing_code(supplier, req.request_id)
            if reuse is not None:
                await self.repo.record_issue(supplier, req.request_id, req.sku, req.order_id, reuse)
                logger.info("Поставщик %s: режим %s, отдаём чужой код %s под request_id=%s",
                            supplier, mode, reuse, req.request_id)
                return IssueResponse(status="ok", request_id=req.request_id, code=reuse)
            # Дублировать нечего (пустой журнал), ведём себя нормально.

        # «ошибка, но код выдан»: резервируем реальный код (списываем инвентарь и
        # фиксируем выдачу), а клиенту возвращаем 500, поэтому ответ теряется, код есть.
        if mode == "error_but_issue":
            code = await self.repo.reserve_code(supplier, req.request_id, req.sku, req.order_id)
            if code is None:
                raise HTTPException(status_code=409, detail={"status": "error", "reason": "out_of_stock"})
            logger.info("Поставщик %s: выдал code=%s, но отвечает 500 (request_id=%s)",
                        supplier, code, req.request_id)
            raise HTTPException(status_code=500, detail={"status": "error", "reason": "issued_but_error"})

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

        # 4) Выдаём код (коммит до искусственной задержки, поэтому таймаут реально
        #    означает «код выдан, но ответ потерян»).
        code = await self.repo.reserve_code(supplier, req.request_id, req.sku, req.order_id)
        if code is None:
            raise HTTPException(status_code=409, detail={"status": "error", "reason": "out_of_stock"})

        # 5) Ловушка таймаута: отвечаем медленнее клиентского таймаута. Код уже
        #    сохранён; клиент повторит с тем же request_id.
        if do_timeout:
            logger.info("Поставщик %s: таймаут после выдачи request_id=%s", supplier, req.request_id)
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

    async def list_issues(self, supplier: str):
        rows = await self.repo.list_issues(supplier.upper())
        return [
            {"request_id": r["request_id"], "code": r["code"],
             "sku": r["sku"], "order_id": r["order_id"]}
            for r in rows
        ]

    async def find_issue(self, supplier: str, request_id: str):
        return await self.repo.find_issue(supplier.upper(), request_id)