"""Автосверка с недоверенным поставщиком (условие 4).

Периодически сравнивает нашу таблицу deliveries с аудит-выгрузкой поставщика
(`GET /{s}/issues`). Утёкшие коды (поставщик выдал, но ответил ошибкой)
привязываются без второй выдачи. Дубли и чужие коды, рассинхрон кода и случай
«возвращено, но выдано» пишутся в журнал supplier_discrepancies для разбора
без ручного вмешательства."""

from app.internal.pkg.config import config
from app.internal.pkg.models.reconcile import IntegrityReport
from app.internal.repository.postgresql.deliveries import (ALREADY_BOUND, BOUND,
                                                           DeliveryRepo)
from app.internal.repository.postgresql.discrepancy import DiscrepancyRepo
from app.internal.repository.postgresql.order_items import OrderItemRepo
from app.internal.services.delivery_service import DeliveryService
from app.pkg.clients.supplier_client import SupplierClient
from app.pkg.logger.events import log_event

__all__ = ["IntegrityService"]


class IntegrityService:
    def __init__(
        self,
        supplier_client: SupplierClient,
        delivery_repo: DeliveryRepo,
        item_repo: OrderItemRepo,
        discrepancy_repo: DiscrepancyRepo,
        delivery_service: DeliveryService,
    ):
        self.client = supplier_client
        self.delivery_repo = delivery_repo
        self.item_repo = item_repo
        self.discrepancy_repo = discrepancy_repo
        self.delivery_service = delivery_service

    @staticmethod
    def _item_of(request_id: str, supplier: str):
        """Вернуть item_id из request_id '{item_id}:{supplier}' (или None, если чужой формат)."""
        parts = request_id.rsplit(":", 1)
        if len(parts) == 2 and parts[1] == supplier:
            return parts[0]
        return None

    async def audit(self) -> IntegrityReport:
        reclaimed = 0
        recorded = 0
        for supplier in config.SUPPLIER_ORDER:
            issues = await self.client.list_issues(supplier)

            # 1) Дубли на стороне поставщика: один код под несколькими request_id.
            by_code: dict[str, set] = {}
            for iss in issues:
                by_code.setdefault(iss["code"], set()).add(iss["request_id"])
            for code, rids in by_code.items():
                if len(rids) > 1:
                    await self.discrepancy_repo.record(
                        supplier=supplier, kind="duplicate_code", code=code,
                        detail=f"один код выдан под {len(rids)} request_id: {sorted(rids)}",
                    )
                    recorded += 1

            # 2) Построчная сверка нашего состояния с аудитом поставщика.
            for iss in issues:
                rid, code = iss["request_id"], iss["code"]
                item_id = self._item_of(rid, supplier)
                if item_id is None:
                    continue

                delivered = await self.delivery_repo.get(item_id)
                if delivered:
                    if delivered["code"] != code:
                        await self.discrepancy_repo.record(
                            supplier=supplier, kind="code_mismatch", request_id=rid,
                            item_id=item_id, code=code,
                            detail=f"выдали {delivered['code']}, аудит: {code}",
                        )
                        recorded += 1
                    continue

                item = await self.item_repo.get_basic(item_id)
                if item is None:
                    continue
                if item["status"] == "refunded":
                    await self.discrepancy_repo.record(
                        supplier=supplier, kind="refunded_but_issued", request_id=rid,
                        item_id=item_id, order_id=item["order_id"], code=code,
                        detail="строка возвращена, но поставщик выдал код",
                    )
                    recorded += 1
                    continue
                if item["status"] == "delivered":
                    continue  # уже выдано другим кодом/путём - увидим на след. проходе
                if item["status"] not in ("paid", "delivering"):
                    continue  # реклеймим только оплаченную, ещё не выданную строку

                # «Утёкший» код: поставщик выдал, мы не привязали, поэтому
                # реклеймим без второй выдачи (условие 3). CODE_CONFLICT пишется в _claim.
                claim = await self.delivery_service._claim(
                    item_id, item["order_id"], item["sku"], supplier, rid, code,
                    item["amount"], item["currency"],
                )
                if claim in (BOUND, ALREADY_BOUND):
                    reclaimed += 1
                    log_event("Автосверка: привязан утёкший код поставщика",
                              supplier=supplier, item_id=item_id, request_id=rid, code=code)
                else:
                    recorded += 1

        open_total = await self.discrepancy_repo.count_open()
        if reclaimed or recorded:
            log_event("Автосверка с поставщиком", reclaimed=reclaimed,
                      recorded=recorded, open_total=open_total)
        return IntegrityReport(reclaimed=reclaimed, recorded=recorded, open_total=open_total)

    async def open_discrepancies(self) -> list[dict]:
        rows = await self.discrepancy_repo.list_open()
        return [dict(r) for r in rows]
