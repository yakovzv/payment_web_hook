"""Автовыдача кода из заглушек-поставщиков: ровно один раз и с правильной
обработкой таймаута (повтор тем же request_id, без второй выдачи)."""

import asyncio

from app.internal.pkg.config import config
from app.internal.pkg.models.delivery import DeliveryResult
from app.internal.repository.postgresql.deliveries import DeliveryRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.internal.repository.postgresql.outbox import OutboxRepo
from app.internal.repository.postgresql.stock import StockRepo
from app.internal.repository.postgresql.uow import transaction
from app.pkg.clients.supplier_client import SupplierClient
from app.pkg.logger.events import log_event

__all__ = ["DeliveryService"]


class DeliveryService:
    def __init__(
        self,
        supplier_client: SupplierClient,
        delivery_repo: DeliveryRepo,
        order_repo: OrderRepo,
        outbox_repo: OutboxRepo,
        stock_repo: StockRepo,
    ):
        self.client = supplier_client
        self.delivery_repo = delivery_repo
        self.order_repo = order_repo
        self.outbox_repo = outbox_repo
        self.stock_repo = stock_repo

    # ---- queue plumbing ----------------------------------------------------

    async def process_once(self) -> int:
        ids = await self.outbox_repo.claim_batch(config.DELIVERY_BATCH_SIZE)
        for order_id in ids:
            try:
                await self.deliver(order_id)
            except Exception as exc:  # ни один заказ не должен обрушить цикл
                log_event("Ошибка выдачи", order_id=order_id, error=str(exc))
                await self._reschedule(order_id, f"exception:{exc}")
        return len(ids)

    async def reclaim_stuck(self) -> int:
        return await self.outbox_repo.reclaim_stuck(config.STUCK_PROCESSING_SEC)

    # ---- выдача ------------------------------------------------------------

    async def deliver(self, order_id: str) -> DeliveryResult:
        # Быстрый путь: уже выдано -> идемпотентная пустая операция.
        existing = await self.delivery_repo.get(order_id)
        if existing:
            await self.outbox_repo.mark_done(order_id)
            return DeliveryResult(order_id=order_id, delivered=True,
                                  supplier=existing["supplier"], code=existing["code"],
                                  status="delivered", detail="already_delivered")

        order = await self.order_repo.get_basic(order_id)
        if order is None:
            return DeliveryResult(order_id=order_id, delivered=False,
                                  status="missing", detail="order_not_found")
        sku = order["sku"]
        async with transaction() as conn:
            await self.order_repo.set_status(conn, order_id, "delivering")
        log_event("Начата выдача", order_id=order_id, sku=sku)

        outcomes = []
        for supplier in config.SUPPLIER_ORDER:
            outcome, code, request_id = await self._try_supplier(supplier, order_id, sku)
            outcomes.append(outcome)

            if outcome == "ok":
                bound = await self._bind(order_id, supplier, request_id, code, sku)
                if bound:
                    log_event("Товар выдан", order_id=order_id, supplier=supplier,
                              request_id=request_id, code=code)
                    return DeliveryResult(order_id=order_id, delivered=True,
                                          supplier=supplier, code=code, status="delivered")
                # Другой путь привязал код первым -> заказ в любом случае выдан.
                await self.outbox_repo.mark_done(order_id)
                return DeliveryResult(order_id=order_id, delivered=True, status="delivered",
                                      detail="bound_concurrently")

            if outcome == "timeout":
                # НЕОДНОЗНАЧНО: A мог выдать. НЕ переключаемся. Повторим тот же rid позже.
                await self._reschedule(order_id, f"timeout:{supplier}")
                log_event("Таймаут поставщика, повтор того же request_id", order_id=order_id,
                          supplier=supplier, request_id=request_id)
                return DeliveryResult(order_id=order_id, delivered=False,
                                      status="delivering", detail=f"timeout:{supplier}")

            # out_of_stock / error -> окончательно, безопасно переключиться на следующего поставщика.
            log_event("Переключение на резервного поставщика", order_id=order_id,
                      supplier=supplier, outcome=outcome, request_id=request_id)

        # Все поставщики исчерпаны с окончательными отказами -> восстановимое состояние.
        final = "out_of_stock" if all(o == "out_of_stock" for o in outcomes) else "delivery_failed"
        async with transaction() as conn:
            await self.order_repo.set_status(conn, order_id, final)
        await self._reschedule(order_id, f"exhausted:{','.join(outcomes)}")
        log_event("Поставщики исчерпаны", order_id=order_id, status=final, outcomes=outcomes)
        return DeliveryResult(order_id=order_id, delivered=False, status=final)

    async def _try_supplier(self, supplier: str, order_id: str, sku: str):
        """Попытка одного поставщика с повторами в рамках вызова, повторно используя
        СТАБИЛЬНЫЙ request_id.
        Возвращает (final_outcome, code|None, request_id)."""
        request_id = f"{order_id}:{supplier}"
        outcome = "error"
        for attempt in range(config.SUPPLIER_MAX_RETRIES + 1):
            outcome, resp = await self.client.issue(supplier, request_id, sku, order_id)
            if outcome == "ok":
                return "ok", resp.code, request_id
            if outcome == "out_of_stock":
                return "out_of_stock", None, request_id
            # error/timeout: короткая задержка, повтор ТОГО ЖЕ request_id (идемпотентно).
            if attempt < config.SUPPLIER_MAX_RETRIES:
                await asyncio.sleep(config.SUPPLIER_BACKOFF_BASE_SEC * (2 ** attempt))
        return outcome, None, request_id  # 'error' -> переключение; 'timeout' -> без переключения

    async def _bind(self, order_id, supplier, request_id, code, sku) -> bool:
        """Привязать код и завершить заказ в одной транзакции.
        Возвращает False, если заказ уже был выдан."""
        async with transaction() as conn:
            bound = await self.delivery_repo.bind(
                conn, order_id=order_id, supplier=supplier,
                request_id=request_id, code=code,
            )
            if not bound:
                return False
            await self.order_repo.mark_delivered(conn, order_id)
            await self.outbox_repo.mark_done(order_id, conn=conn)
            await self.stock_repo.decrement(conn, sku)
            return True

    async def _reschedule(self, order_id, reason):
        await self.outbox_repo.reschedule(
            order_id, reason,
            config.SUPPLIER_BACKOFF_BASE_SEC, config.DELIVERY_MAX_BACKOFF_SEC,
        )