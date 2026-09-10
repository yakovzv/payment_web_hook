"""История/темпоральность: восстановление точного состояния заказа и денег на
любой прошлый момент из append-only логов (order_events + ledger_entries) и
сходящиеся итоги за период."""

import json
from datetime import datetime

from app.internal.pkg.models.history import (AccountBalance, LedgerAtView,
                                             OrderAtView, OrderItemAt,
                                             PeriodAccount, PeriodReport)
from app.internal.repository.postgresql.event import EventRepo
from app.internal.repository.postgresql.ledger import LedgerRepo

__all__ = ["HistoryService"]


def _balances(rows) -> list[AccountBalance]:
    return [
        AccountBalance(account=r["account"], debit=r["debit"], credit=r["credit"],
                       balance=r["credit"] - r["debit"])
        for r in rows
    ]


class HistoryService:
    def __init__(self, event_repo: EventRepo, ledger_repo: LedgerRepo):
        self.event_repo = event_repo
        self.ledger_repo = ledger_repo

    async def order_at(self, order_id: str, ts: datetime) -> OrderAtView:
        """Свернуть события заказа до момента ts и вернуть состояние на тот момент."""
        events = await self.event_repo.for_order_asof(order_id, ts)
        money = _balances(await self.ledger_repo.balances_asof(ts, order_id))

        if not events:
            return OrderAtView(order_id=order_id, as_of=ts, exists=False,
                               status="absent", items=[], money=money)

        items: dict[str, dict] = {}
        has_payment = has_failed = False
        for e in events:
            t = e["type"]
            p = json.loads(e["payload"]) if e["payload"] else {}
            if t == "item_created":
                items[e["item_id"]] = {
                    "id": e["item_id"], "sku": p.get("sku"), "amount": p.get("amount", 0),
                    "status": "created", "code": None, "supplier": None,
                }
            elif t == "payment_received":
                has_payment = True
            elif t == "payment_failed":
                has_failed = True
            elif t == "item_delivered":
                it = items.get(e["item_id"])
                if it:
                    it.update(status="delivered", code=p.get("code"), supplier=p.get("supplier"))
            elif t == "item_refunded":
                it = items.get(e["item_id"])
                if it:
                    it["status"] = "refunded"

        # Оплата переводит ещё не терминальные строки в 'paid'.
        for it in items.values():
            if it["status"] == "created" and has_payment:
                it["status"] = "paid"

        statuses = [it["status"] for it in items.values()]
        status = self._order_status(statuses, has_payment, has_failed)

        return OrderAtView(
            order_id=order_id, as_of=ts, exists=True, status=status,
            items=[OrderItemAt(**it) for it in items.values()],
            money=money,
        )

    @staticmethod
    def _order_status(statuses, has_payment, has_failed) -> str:
        if has_failed and not has_payment:
            return "payment_failed"
        if not statuses:
            return "created"
        terminal = {"delivered", "refunded"}
        if all(s in terminal for s in statuses):
            if all(s == "delivered" for s in statuses):
                return "delivered"
            if all(s == "refunded" for s in statuses):
                return "refunded"
            return "partially_delivered"
        if has_payment:
            return "delivering"
        return "created"

    async def ledger_at(self, ts: datetime) -> LedgerAtView:
        accounts = _balances(await self.ledger_repo.balances_asof(ts))
        net = sum(a.balance for a in accounts)
        return LedgerAtView(as_of=ts, accounts=accounts, balanced=(net == 0))

    async def period_report(self, dt_from: datetime, dt_to: datetime) -> PeriodReport:
        opening = {a.account: a.balance for a in _balances(await self.ledger_repo.balances_asof(dt_from))}
        closing = {a.account: a.balance for a in _balances(await self.ledger_repo.balances_asof(dt_to))}
        moves = await self.ledger_repo.movements(dt_from, dt_to)

        accounts, all_consistent = [], True
        by_move = {}
        for m in moves:
            net = m["credit"] - m["debit"]
            by_move[m["account"]] = m
            acc = m["account"]
            op, cl = opening.get(acc, 0), closing.get(acc, 0)
            consistent = (cl == op + net)   # два независимых пути (as-of vs период)
            all_consistent = all_consistent and consistent
            accounts.append(PeriodAccount(
                account=acc, opening=op, closing=cl,
                debit=m["debit"], credit=m["credit"], movement=net, consistent=consistent,
            ))

        def credit(acc):
            m = by_move.get(acc)
            return m["credit"] if m else 0

        total_debit = sum(m["debit"] for m in moves)
        total_credit = sum(m["credit"] for m in moves)
        return PeriodReport(
            from_ts=dt_from, to_ts=dt_to, accounts=accounts,
            payments=credit("customer_funds"),
            revenue=credit("revenue"),
            refunds=credit("refunds"),
            double_entry_balanced=(total_debit == total_credit),
            consistent=all_consistent,
        )
