"""Этап 7 (недоверенный поставщик): ответу /issue доверять нельзя. Гарантируем
сами - один код не уйдёт в два заказа, покупатель получит ровно один рабочий код,
повтор не приводит ко второй выдаче, расхождения находятся автосверкой."""

import uuid

from conftest import (STORE, SUPPLIERS, create_order, deliveries_count,
                      send_webhook, set_supplier, supplier_status, wait_for)


async def _integrity(http):
    async with http.get(f"{STORE}/admin/integrity") as r:
        return await r.json()


async def _audit(http):
    async with http.post(f"{STORE}/admin/integrity/audit") as r:
        return await r.json()


async def _code_orders(db, code):
    """Сколько РАЗНЫХ заказов держат данный код (должно быть <= 1)."""
    return await db.fetchval(
        "SELECT count(DISTINCT order_id) FROM deliveries WHERE code=$1", code
    )


async def test_error_but_issue_no_double(http, db):
    # Условие 3: поставщик ответил ошибкой, но код выдал -> повтор без второй выдачи,
    # без ошибочного fallback на B.
    await set_supplier(http, "A", mode="error_but_issue")
    await set_supplier(http, "B", mode="always_error")
    before_a = (await supplier_status(http, "A"))["issued"]
    before_b = (await supplier_status(http, "B"))["issued"]

    order = await create_order(http, sku="KEY-CS2-PRIME")
    await send_webhook(http, order["id"])

    final = await wait_for(http, order["id"], {"delivered"}, timeout=30.0)
    assert final["status"] == "delivered"
    assert final["supplier"] == "A"                       # выдал A, не резерв
    assert final["code"]
    assert await deliveries_count(db, order["id"]) == 1

    after_a = (await supplier_status(http, "A"))["issued"]
    after_b = (await supplier_status(http, "B"))["issued"]
    assert after_a == before_a + 1                        # ровно один код списан у A
    assert after_b == before_b                            # B не трогали


async def test_foreign_code_never_double_assigned(http, db):
    # Условия 1 и 2: поставщик отдаёт уже выданный кому-то код -> отвергаем,
    # покупатель получает свой валидный код, чужой код не уходит во второй заказ.
    await set_supplier(http, "A", mode="normal")
    await set_supplier(http, "B", mode="normal")

    o1 = await create_order(http, sku="KEY-CS2-PRIME")
    await send_webhook(http, o1["id"])
    o1f = await wait_for(http, o1["id"], {"delivered"}, timeout=30.0)
    assert o1f["status"] == "delivered"
    code_c = o1f["code"]
    assert o1f["supplier"] == "A"

    # Теперь A «ворует» и отдаёт уже выданный код C любому новому заказу.
    await set_supplier(http, "A", mode="foreign_code")
    o2 = await create_order(http, sku="KEY-GTA5")
    await send_webhook(http, o2["id"])
    o2f = await wait_for(http, o2["id"], {"delivered"}, timeout=30.0)

    assert o2f["status"] == "delivered"
    assert o2f["supplier"] == "B"                         # A забракован -> fallback на B
    assert o2f["code"] and o2f["code"] != code_c          # свой, другой код
    assert await deliveries_count(db, o2["id"]) == 1
    # Код C принадлежит РОВНО одному заказу.
    assert await _code_orders(db, code_c) == 1

    # Условие 4: расхождение обнаружено автоматически.
    await _audit(http)
    report = await _integrity(http)
    kinds = {d["kind"] for d in report["open"]}
    assert report["count"] >= 1
    assert "foreign_code" in kinds or "duplicate_code" in kinds

    # Деньги не пострадали от вранья поставщика.
    async with http.get(f"{STORE}/admin/reconcile") as r:
        rec = await r.json()
    assert rec["ledger"]["balanced"] is True
    assert rec["money_mismatch"] == []


async def test_audit_reclaims_leaked_code(http, db):
    # Условия 3 и 4 (фоновая ветка): поставщик выдал код, но мы его не привязали
    # (ответ потерян) -> автосверка находит и привязывает его без второй выдачи.
    oid = f"ord_leak_{uuid.uuid4().hex[:10]}"
    iid = f"itm_leak_{uuid.uuid4().hex[:10]}"
    rid = f"{iid}:A"
    code = f"LEAK-{uuid.uuid4().hex[:8].upper()}"
    amount = 500

    # Оплаченная строка без выдачи; платёж проведён в журнале; задача помечена done,
    # чтобы обычный конвейер выдачи её не трогал - довести должна только автосверка.
    await db.execute(
        "INSERT INTO orders (id, sku, amount, currency, status, paid_at) "
        "VALUES ($1,'STEAM-TOPUP-500',$2,'RUB','paid', now())", oid, amount)
    await db.execute(
        "INSERT INTO order_items (id, order_id, sku, amount, currency, status) "
        "VALUES ($1,$2,'STEAM-TOPUP-500',$3,'RUB','paid')", iid, oid, amount)
    await db.execute(
        """INSERT INTO ledger_entries (order_id,event_id,account,direction,amount,currency)
           VALUES ($1,$2,'cash','debit',$3,'RUB'),
                  ($1,$2,'customer_funds','credit',$3,'RUB')""",
        oid, f"evt_leak_{iid}", amount)
    await db.execute(
        "INSERT INTO delivery_outbox (item_id, order_id, status) VALUES ($1,$2,'done')",
        iid, oid)
    await db.execute(
        "INSERT INTO supplier_issues (supplier, request_id, sku, order_id, code) "
        "VALUES ('A',$1,'STEAM-TOPUP-500',$2,$3)", rid, oid, code)

    # Триггерим сверку явно (фоновый воркер тоже её делает - реклейм идемпотентен).
    await _audit(http)

    final = await wait_for(http, oid, {"delivered"}, timeout=15.0)
    assert final["status"] == "delivered"
    assert final["code"] == code                          # привязан именно утёкший код
    assert await deliveries_count(db, oid) == 1

    # Повторная сверка ничего не дублирует.
    await _audit(http)
    assert await deliveries_count(db, oid) == 1

    async with http.get(f"{STORE}/admin/reconcile") as r:
        rec = await r.json()
    assert rec["ledger"]["balanced"] is True
    assert rec["money_mismatch"] == []
