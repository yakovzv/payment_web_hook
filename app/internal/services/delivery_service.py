"""Автовыдача кодов по строкам заказа при недоверенном поставщике.

Ответу /issue доверять нельзя: он может вернуть дубль или чужой код либо
ответить ошибкой, уже выдав код. Поэтому один код не уходит в два заказа,
покупатель получает ровно один рабочий код, а повтор не приводит ко второй
выдаче. Расхождения с поставщиком пишутся в журнал и разбираются фоново."""

import asyncio

from app.internal.pkg.config import config
from app.internal.pkg.models.delivery import DeliveryResult
from app.internal.repository.postgresql.deliveries import (ALREADY_BOUND, BOUND,
                                                           CODE_CONFLICT, DeliveryRepo)
from app.internal.repository.postgresql.discrepancy import DiscrepancyRepo
from app.internal.repository.postgresql.event import EventRepo
from app.internal.repository.postgresql.ledger import LedgerRepo
from app.internal.repository.postgresql.order_items import OrderItemRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.internal.repository.postgresql.outbox import OutboxRepo
from app.internal.repository.postgresql.rate_limit import RateLimitRepo
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
        item_repo: OrderItemRepo,
        outbox_repo: OutboxRepo,
        ledger_repo: LedgerRepo,
        stock_repo: StockRepo,
        discrepancy_repo: DiscrepancyRepo,
        rate_limit_repo: RateLimitRepo,
        event_repo: EventRepo,
    ):
        self.client = supplier_client
        self.delivery_repo = delivery_repo
        self.order_repo = order_repo
        self.item_repo = item_repo
        self.outbox_repo = outbox_repo
        self.ledger_repo = ledger_repo
        self.stock_repo = stock_repo
        self.discrepancy_repo = discrepancy_repo
        self.rate_limit = rate_limit_repo
        self.event_repo = event_repo

    async def process_once(self) -> int:
        item_ids = await self.outbox_repo.claim_batch(config.DELIVERY_BATCH_SIZE)
        for item_id in item_ids:
            try:
                await self.deliver_item(item_id)
            except Exception as exc:  # ни одна строка не должна обрушить цикл
                log_event("Ошибка выдачи строки", item_id=item_id, error=str(exc))
                await self._reschedule(item_id, f"exception:{exc}")
        return len(item_ids)

    async def reclaim_stuck(self) -> int:
        return await self.outbox_repo.reclaim_stuck(config.STUCK_PROCESSING_SEC)

    async def redeliver_order(self, order_id: str) -> DeliveryResult:
        """Ручной повтор: доводит все незавершённые строки заказа. Идемпотентно."""
        async with transaction() as conn:
            item_ids = await self.item_repo.ids_for_order(conn, order_id)
        if not item_ids:
            return DeliveryResult(order_id=order_id, delivered=False,
                                  status="missing", detail="order_not_found")
        for item_id in item_ids:
            try:
                await self.deliver_item(item_id)
            except Exception as exc:
                log_event("Ошибка выдачи строки", item_id=item_id, error=str(exc))
                await self._reschedule(item_id, f"exception:{exc}")
        order = await self.order_repo.get_basic(order_id)
        return DeliveryResult(order_id=order_id,
                              delivered=bool(order and order["status"] == "delivered"),
                              status=order["status"] if order else "missing")

    async def deliver_item(self, item_id: str) -> DeliveryResult:
        item = await self.item_repo.get_basic(item_id)
        if item is None:
            await self.outbox_repo.mark_done(item_id)
            return DeliveryResult(order_id="", item_id=item_id, delivered=False,
                                  status="missing", detail="item_not_found")
        order_id, sku = item["order_id"], item["sku"]
        amount, currency = item["amount"], item["currency"]

        # Быстрый путь: строка уже выдана, идемпотентно закрываем задачу.
        existing = await self.delivery_repo.get(item_id)
        if existing:
            await self._finalize_delivered(item_id, order_id, amount, currency)
            return DeliveryResult(order_id=order_id, item_id=item_id, delivered=True,
                                  supplier=existing["supplier"], code=existing["code"],
                                  status="delivered", detail="already_delivered")

        if item["status"] == "refunded":
            await self.outbox_repo.mark_done(item_id)
            return DeliveryResult(order_id=order_id, item_id=item_id, delivered=False,
                                  refunded=True, status="refunded", detail="already_refunded")

        async with transaction() as conn:
            await self.item_repo.set_status(conn, item_id, "delivering")
            await self.order_repo.mark_delivering(conn, order_id)
        log_event("Начата выдача строки", order_id=order_id, item_id=item_id, sku=sku)

        outcomes = []
        rate_limited = False
        for supplier in config.SUPPLIER_ORDER:
            outcome, code, request_id = await self._try_supplier(supplier, item_id, sku, order_id)

            if outcome == "rate_limited":
                # Лимит поставщика исчерпан в этом окне: не спрашиваем и не теряем
                # задачу, это не сбой. Она подождёт ёмкости (см. ниже).
                rate_limited = True
                continue

            if outcome == "ok":
                # Ответу не доверяем: код проверяется атомарной привязкой.
                claim = await self._claim(item_id, order_id, sku, supplier,
                                          request_id, code, amount, currency)
                if claim in (BOUND, ALREADY_BOUND):
                    log_event("Товар выдан", order_id=order_id, item_id=item_id,
                              supplier=supplier, request_id=request_id, code=code)
                    return DeliveryResult(order_id=order_id, item_id=item_id, delivered=True,
                                          supplier=supplier, code=code if claim == BOUND else None,
                                          status="delivered")
                # CODE_CONFLICT: чужой/дублирующий код отвергнут (расхождение записано).
                outcomes.append("conflict")
                log_event("Поставщик прислал чужой/дублирующий код - отвергнут",
                          order_id=order_id, item_id=item_id, supplier=supplier, code=code)
                continue

            if outcome == "timeout":
                # Неоднозначно: код мог быть выдан. Не переключаемся, повтор тем же rid.
                await self._reschedule(item_id, f"timeout:{supplier}")
                log_event("Таймаут поставщика, повтор того же request_id",
                          order_id=order_id, item_id=item_id, supplier=supplier,
                          request_id=request_id)
                return DeliveryResult(order_id=order_id, item_id=item_id, delivered=False,
                                      status="delivering", detail=f"timeout:{supplier}")

            # error / out_of_stock: ответу не доверяем, вдруг код всё же выдан.
            # Сверяемся с аудит-каналом поставщика перед fallback (условие 3).
            leaked = await self.client.get_issue(supplier, request_id)
            if leaked:
                claim = await self._claim(item_id, order_id, sku, supplier,
                                          request_id, leaked, amount, currency)
                if claim in (BOUND, ALREADY_BOUND):
                    log_event("Ошибка поставщика, но код выдан - привязан без второй выдачи",
                              order_id=order_id, item_id=item_id, supplier=supplier,
                              request_id=request_id, code=leaked)
                    return DeliveryResult(order_id=order_id, item_id=item_id, delivered=True,
                                          supplier=supplier, code=leaked if claim == BOUND else None,
                                          status="delivered")
                # Утёкший код принадлежит другой строке: расхождение записано, fallback.

            outcomes.append(outcome)
            log_event("Переключение на резервного поставщика", order_id=order_id,
                      item_id=item_id, supplier=supplier, outcome=outcome, request_id=request_id)

        # Хотя бы у одного поставщика не было ёмкости, поэтому ждём окна, а не
        # возвращаем: заказ не теряется и лимит не превышается (бэкпрешер).
        if rate_limited:
            await self.outbox_repo.defer(item_id, "rate_limited", config.RATE_LIMIT_DEFER_SEC)
            log_event("Лимит поставщика: заказ ждёт ёмкости", order_id=order_id, item_id=item_id)
            return DeliveryResult(order_id=order_id, item_id=item_id, delivered=False,
                                  status="delivering", detail="rate_limited")

        # Все поставщики ответили детерминированным отказом: честный возврат строки.
        return await self._refund(item_id, order_id, amount, currency, outcomes)

    async def _try_supplier(self, supplier: str, item_id: str, sku: str, order_id: str):
        """Попытка одного поставщика с повторами тем же стабильным request_id.
        Каждый реальный вызов /issue берёт токен лимита, поэтому лимит не
        превышается. Возвращает (final_outcome, code|None, request_id); outcome
        может быть 'rate_limited', если ни одного запроса не сделали (нет ёмкости)."""
        request_id = f"{item_id}:{supplier}"
        outcome = "error"
        for attempt in range(config.SUPPLIER_MAX_RETRIES + 1):
            if not await self.rate_limit.try_acquire(supplier):
                if attempt == 0:
                    # Ещё ни разу не спрашивали в этом окне: честный бэкпрешер.
                    return "rate_limited", None, request_id
                break  # уже потратили токен(ы) на повторы - не долбим лимит дальше
            outcome, resp = await self.client.issue(supplier, request_id, sku, order_id)
            if outcome == "ok":
                return "ok", resp.code, request_id
            if outcome == "out_of_stock":
                return "out_of_stock", None, request_id
            # error/timeout: короткая задержка, повтор того же request_id (идемпотентно).
            if attempt < config.SUPPLIER_MAX_RETRIES:
                await asyncio.sleep(config.SUPPLIER_BACKOFF_BASE_SEC * (2 ** attempt))
        return outcome, None, request_id  # 'error': следующий поставщик; 'timeout': без переключения

    async def _claim(self, item_id, order_id, sku, supplier, request_id, code,
                     amount, currency) -> str:
        """Атомарно проверить и закрепить код за строкой. Возвращает статус
        привязки (BOUND / ALREADY_BOUND / CODE_CONFLICT). Финализирует выдачу
        только когда код действительно принадлежит этой строке; списывает остаток
        ровно один раз (только на первичной привязке)."""
        async with transaction() as conn:
            status = await self.delivery_repo.bind(
                conn, item_id=item_id, order_id=order_id, sku=sku,
                supplier=supplier, request_id=request_id, code=code,
            )
            if status == CODE_CONFLICT:
                owner = await self.delivery_repo.owner_of_code(conn, supplier, code)
                await self.discrepancy_repo.record(
                    conn=conn, supplier=supplier, kind="foreign_code",
                    request_id=request_id, item_id=item_id, order_id=order_id, code=code,
                    detail=f"код закреплён за строкой {owner['item_id'] if owner else '?'}",
                )
                return CODE_CONFLICT

            # Код принадлежит этой строке (BOUND или ALREADY_BOUND): финализируем.
            if status == BOUND:
                await self.stock_repo.decrement(conn, sku)  # ровно один раз
                await self.event_repo.append(
                    conn, order_id=order_id, item_id=item_id, type="item_delivered",
                    payload={"supplier": supplier, "code": code, "amount": amount,
                             "currency": currency},
                )
            await self.item_repo.mark_delivered(conn, item_id)
            await self.ledger_repo.book_delivery(
                conn, item_id=item_id, order_id=order_id, amount=amount, currency=currency,
            )
            await self.outbox_repo.mark_done(item_id, conn=conn)
            await self.item_repo.recompute_order_status(conn, order_id)
            return status

    async def _finalize_delivered(self, item_id, order_id, amount, currency):
        """Идемпотентно закрыть уже выданную строку (быстрый путь). Без списания
        остатка - оно уже произошло на первичной привязке."""
        async with transaction() as conn:
            await self.item_repo.mark_delivered(conn, item_id)
            await self.ledger_repo.book_delivery(
                conn, item_id=item_id, order_id=order_id, amount=amount, currency=currency,
            )
            await self.outbox_repo.mark_done(item_id, conn=conn)
            await self.item_repo.recompute_order_status(conn, order_id)

    async def _refund(self, item_id, order_id, amount, currency, outcomes) -> DeliveryResult:
        """Честный возврат строки: guarded-переход в refunded + проводка возврата +
        закрытие задачи - атомарно. Ровно один возврат на строку."""
        async with transaction() as conn:
            refunded = await self.item_repo.transition_to_refunded(conn, item_id)
            if refunded:
                await self.ledger_repo.book_refund(
                    conn, item_id=item_id, order_id=order_id,
                    amount=amount, currency=currency,
                )
                await self.event_repo.append(
                    conn, order_id=order_id, item_id=item_id, type="item_refunded",
                    payload={"amount": amount, "currency": currency,
                             "outcomes": outcomes},
                )
            await self.outbox_repo.mark_done(item_id, conn=conn)
            await self.item_repo.recompute_order_status(conn, order_id)
        log_event("Строка возвращена (не удалось выдать)", order_id=order_id,
                  item_id=item_id, outcomes=outcomes, amount=amount)
        return DeliveryResult(order_id=order_id, item_id=item_id, delivered=False,
                              refunded=True, status="refunded",
                              detail=f"exhausted:{','.join(outcomes)}")

    async def _reschedule(self, item_id, reason):
        await self.outbox_repo.reschedule(
            item_id, reason,
            config.SUPPLIER_BACKOFF_BASE_SEC, config.DELIVERY_MAX_BACKOFF_SEC,
        )
