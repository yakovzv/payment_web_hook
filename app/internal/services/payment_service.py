"""Обработка вебхуков оплаты: идемпотентно и ровно один раз. Только
бизнес-логика; транзакцией владеет сервис, весь SQL - в репозиториях."""

from app.internal.pkg.models.payment import PaymentWebhook, WebhookAck
from app.internal.repository.postgresql.event import EventRepo
from app.internal.repository.postgresql.ledger import LedgerRepo
from app.internal.repository.postgresql.order_items import OrderItemRepo
from app.internal.repository.postgresql.orders import OrderRepo
from app.internal.repository.postgresql.outbox import OutboxRepo
from app.internal.repository.postgresql.uow import transaction
from app.internal.repository.postgresql.webhook import WebhookRepo
from app.pkg.logger.events import log_event

__all__ = ["PaymentService"]


class PaymentService:
    def __init__(
        self,
        webhook_repo: WebhookRepo,
        order_repo: OrderRepo,
        item_repo: OrderItemRepo,
        ledger_repo: LedgerRepo,
        outbox_repo: OutboxRepo,
        event_repo: EventRepo,
    ):
        self.webhook_repo = webhook_repo
        self.order_repo = order_repo
        self.item_repo = item_repo
        self.ledger_repo = ledger_repo
        self.outbox_repo = outbox_repo
        self.event_repo = event_repo

    async def handle_webhook(self, hook: PaymentWebhook) -> WebhookAck:
        async with transaction() as conn:
            inserted = await self.webhook_repo.insert_event(
                conn,
                event_id=hook.event_id,
                order_id=hook.order_id,
                status=hook.status,
                amount=hook.amount,
                currency=hook.currency,
                payload=hook.model_dump(mode="json"),
            )
            if not inserted:
                # Слой 1: дубликат event_id, пустая операция.
                log_event("Дубликат вебхука оплаты", event_id=hook.event_id, order_id=hook.order_id)
                return WebhookAck(result="duplicate")

            result = await self._apply(
                conn,
                event_id=hook.event_id,
                order_id=hook.order_id,
                status=hook.status,
                amount=hook.amount,
                currency=hook.currency,
            )
            return WebhookAck(result=result)

    async def apply_pending(self, limit: int = 100) -> int:
        """Повторить события вебхуков, которые ещё не удалось применить (например,
        пришли раньше, чем появился заказ). Возвращает число только что применённых."""
        pending = await self.webhook_repo.get_pending(limit)
        applied = 0
        for row in pending:
            async with transaction() as conn:
                result = await self._apply(
                    conn,
                    event_id=row["event_id"],
                    order_id=row["order_id"],
                    status=row["status"],
                    amount=row["amount"],
                    currency=row["currency"],
                )
            if result != "pending":
                applied += 1
        return applied

    async def _apply(self, conn, *, event_id, order_id, status, amount, currency) -> str:
        """Применить одно платёжное событие под блокировкой строки. Должно
        выполняться внутри транзакции."""
        order = await self.order_repo.lock(conn, order_id)
        if order is None:
            # Внеочередное: оставляем событие отложенным; sweeper повторит попытку.
            log_event("Вебхук оплаты отложен", event_id=event_id, order_id=order_id,
                      reason="заказ не найден")
            return "pending"

        if status == "failed":
            updated = await self.order_repo.transition_to_payment_failed(conn, order_id)
            await self.webhook_repo.mark_processed(conn, event_id)
            if updated:
                await self.event_repo.append(
                    conn, order_id=order_id, type="payment_failed",
                    payload={"event_id": event_id},
                )
                log_event("Оплата не прошла", event_id=event_id, order_id=order_id)
                return "applied"
            return "ignored"

        if status == "paid":
            updated = await self.order_repo.transition_to_paid(conn, order_id)
            if updated is None:
                # Уже paid/delivering/delivered/...: идемпотентная пустая операция.
                await self.webhook_repo.mark_processed(conn, event_id)
                return "ignored"

            booked_amount = amount if amount is not None else updated["amount"]
            booked_currency = currency or updated["currency"]
            # Проводка оплаты на сумму заказа (обязательство customer_funds).
            await self.ledger_repo.book_payment(
                conn, order_id=order_id, event_id=event_id,
                amount=booked_amount, currency=booked_currency,
            )
            # Переводим строки в paid и ставим по одной задаче выдачи на каждую -
            # всё в той же транзакции (паттерн outbox: оплаченная строка не может
            # остаться без задачи на выдачу).
            await self.item_repo.mark_paid(conn, order_id)
            for item_id in await self.item_repo.ids_for_order(conn, order_id):
                await self.outbox_repo.enqueue(conn, item_id, order_id)
            await self.event_repo.append(
                conn, order_id=order_id, type="payment_received",
                payload={"event_id": event_id, "amount": booked_amount,
                         "currency": booked_currency},
            )
            await self.webhook_repo.mark_processed(conn, event_id)
            log_event("Оплата проведена", event_id=event_id, order_id=order_id,
                      amount=booked_amount, currency=booked_currency)
            return "applied"

        # Неизвестный статус: подтверждаем, но ничего не делаем.
        await self.webhook_repo.mark_processed(conn, event_id)
        return "ignored"