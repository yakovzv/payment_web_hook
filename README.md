# Ядро магазина цифровых товаров (тестовое задание)

Бэкенд-ядро площадки цифровых товаров: заказы по SKU, приём вебхуков оплаты,
автоматическая выдача кода/ключа из заглушек-поставщиков. Всё построено вокруг
**однократной выдачи** (exactly-once), **корректной обработки таймаутов** и
**восстановления** зависших заказов.

- **Стек:** Python 3.13, FastAPI, PostgreSQL 17 (asyncpg), yoyo-migrations,
  фоновые задачи на asyncio + DB-очередь (outbox). Зависимости через `uv`.
- **Запуск:** Docker Compose (Postgres + приложение + сервис поставщиков + миграции).

Все шесть состязательных сценариев из критериев приёмки закрыты автотестами
(`tests/`, 9 тестов).

---

### Прогон тестов

Тесты идут по «живому» стеку (поднятому `make up`) и проверяют все 6 сценариев
приёмки. Нужен только `uv` на хосте:

```bash
make test          # uv run --group dev pytest -v
```

Ожидаемый результат — `9 passed`. Если стек не поднят, тесты аккуратно
скипаются с подсказкой.

---

## Как воспроизвести проверки

### 1. Гонки: 50 параллельных вебхуков «оплачено» → ровно одна выдача

Тем же скриптом, что эмулирует платёжку:

```bash
# создать заказ, выстрелить 50 параллельных вебхуков, дождаться результата
uv run python scripts/emulate_payment.py demo --count 50
# -> fired 50 parallel webhooks -> {'200:applied': 1, '200:ignored': 49}
# -> final order: {'status': 'delivered', 'code': '...', 'supplier': 'A'}
```

- Ровно **один** вебхук перевёл заказ в `paid` (`applied: 1`), остальные — no-op.
- Итог — один код, один факт выдачи (`deliveries` содержит ровно одну строку).

Повторный вебхук с тем же `event_id` (идемпотентность):

```bash
ORDER=$(uv run python scripts/emulate_payment.py order --sku KEY-CS2-PRIME | python -c "import sys,ast;print(ast.literal_eval(sys.stdin.read())['id'])")
uv run python scripts/emulate_payment.py race --order $ORDER --count 50 --same-event
# -> {'200:applied': 1, '200:duplicate': 49}
```

Автотесты: `tests/test_concurrency.py`.

### 2. Отказ поставщика и fallback A → B


```bash
curl -sX POST localhost:8002/A/config -H 'content-type: application/json' -d '{"mode":"always_error"}'
curl -sX POST localhost:8002/B/config -H 'content-type: application/json' -d '{"mode":"normal"}'

ORDER=$(uv run python scripts/emulate_payment.py order --sku KEY-GTA5 | python -c "import sys,ast;print(ast.literal_eval(sys.stdin.read())['id'])")
uv run python scripts/emulate_payment.py pay --order $ORDER
uv run python scripts/emulate_payment.py get --order $ORDER
# -> status=delivered, supplier=B   (A выдал 0 кодов, B — ровно 1)
```

Автотест: `tests/test_fallback.py`.

### 3. Ловушка таймаута: поставщик успел выдать, но ответ не дошёл

```bash
# A выдаёт код и «зависает» дольше клиентского таймаута; B умышленно ломаем,
# чтобы неверный fallback провалил бы проверку.
curl -sX POST localhost:8002/A/config -d '{"mode":"always_timeout","timeout_delay_sec":8}' -H 'content-type: application/json'
curl -sX POST localhost:8002/B/config -d '{"mode":"always_error"}' -H 'content-type: application/json'

ORDER=$(uv run python scripts/emulate_payment.py order --sku KEY-EFT | python -c "import sys,ast;print(ast.literal_eval(sys.stdin.read())['id'])")
uv run python scripts/emulate_payment.py pay --order $ORDER
uv run python scripts/emulate_payment.py get --order $ORDER
# -> status=delivered, supplier=A;  A.issued увеличился ровно на 1 (нет двойной выдачи)
```

Повтор идёт с **тем же** `request_id`, поэтому поставщик возвращает **тот же**
код, а не выдаёт новый. Автотест: `tests/test_supplier_timeout.py`.

### 4. Пустой остаток → восстановимое состояние → восстановление

```bash
curl -sX POST localhost:8002/A/config -d '{"mode":"always_oos"}' -H 'content-type: application/json'
curl -sX POST localhost:8002/B/config -d '{"mode":"always_oos"}' -H 'content-type: application/json'
# оплатить заказ -> он уйдёт в out_of_stock без падения
# затем вернуть остаток и вызвать восстановление:
curl -sX POST localhost:8002/A/config -d '{"mode":"normal"}' -H 'content-type: application/json'
curl -sX POST localhost:8001/admin/recover
# -> заказ доводится до delivered, ровно один код
```

Автотест: `tests/test_out_of_stock_recovery.py`.

### 5. Сверка и денежный журнал

```bash
make reconcile
# {"paid_not_delivered": [...], "delivered_not_paid": [], "ledger": {"balanced": true}}
```

### 6. Каталог под нагрузкой (Stage 5): план запроса витрины

```bash
make load          # зальёт ~5000 SKU и покажет EXPLAIN (ANALYZE, BUFFERS)
```

---

## Модель данных

| Таблица | Назначение | Ключевые гарантии |
|---|---|---|
| `products`, `stock` | каталог + денормализованный счётчик остатка | «горячий» запрос витрины O(1) на строку |
| `orders` | жизненный цикл заказа | статусный переход под блокировкой строки |
| `webhook_events` | инбокс вебхуков (at-least-once) | `event_id` PK → дедуп |
| `deliveries` | выданный код, привязанный к заказу | `order_id` PK + UNIQUE(supplier, code) → **не более одной выдачи** |
| `delivery_outbox` | DB-очередь фоновой выдачи | claim через `FOR UPDATE SKIP LOCKED` |
| `ledger_entries` | двойная запись движений денег | `sum(debit) == sum(credit)` всегда |
| `supplier_inventory`, `supplier_issues`, `supplier_config` | заглушки поставщиков | идемпотентность по `request_id`, инъекция отказов |

Статусы заказа: `created → paid → delivering → delivered`; ветки
`payment_failed` (финальный), `out_of_stock` / `delivery_failed` (восстановимые).

---

## Ключевые решения

**Exactly-once по оплате (Этап 2).** Две независимые линии обороны:
1. *Дедуп инбокса* — `INSERT INTO webhook_events(event_id) ON CONFLICT DO NOTHING`.
   Работу делает только первое появление конкретного `event_id`; повторы — no-op
   (критерий 2).
2. *Переход под защитой состояния* — `UPDATE orders SET status='paid'
   WHERE status='created'` под блокировкой строки. Из N параллельных вебхуков по
   одному заказу ровно один меняет состояние и ставит задачу на выдачу; остальные —
   no-op (критерий 1). Задача выдачи ставится в **той же транзакции** (паттерн
   outbox) — оплаченный заказ не может остаться без задачи на выдачу.

Вебхук «раньше заказа» (критерий 3): событие всегда сохраняется; если заказа ещё
нет — остаётся `processed=false` и применяется свипером/`/admin/recover`, когда
заказ появится.

**Exactly-once по выдаче (Этапы 1, 3).** Три замка:
- claim задачи из `delivery_outbox` через `FOR UPDATE SKIP LOCKED` → один воркер
  на заказ;
- `deliveries.order_id` PRIMARY KEY → максимум один код на заказ;
- идемпотентность поставщика по `request_id` → повтор возвращает тот же код.

**Ловушка таймаута (Этап 3) — главное.** `request_id` **стабилен** для пары
(заказ, поставщик): `f"{order_id}:{supplier}"`. Отсюда правило:
`таймаут ≠ отказ`. При таймауте поставщик мог успеть выдать код, поэтому мы
**никогда не делаем fallback по таймауту** — повторяем **тот же** `request_id`
(сначала в рамках вызова, затем фоново), и получаем уже выданный код. Fallback на
B делается только при **детерминированном** отрицании A (`out_of_stock` или
`5xx`/недоступность) — по контракту это значит, что код не выдавался. Заглушка
моделирует ровно эту ситуацию: в режиме `always_timeout` она сначала фиксирует
выдачу в БД (commit), и только потом «висит» — так что ответ теряется, а код уже
существует.

**Наблюдаемость и восстановление (Этап 4).** Структурированные (JSON) события на
всех денежных/выдачных переходах («Заказ создан», «Оплата проведена», «Товар
выдан», «Таймаут поставщика, повтор того же request_id», …) с корреляцией по
`order_id/event_id/request_id/supplier`. Эндпоинт `GET /admin/reconcile` даёт
срез «оплачен-не-выдан» / «выдан-не-оплачен» и проверку баланса журнала. Фоновый
recovery-воркер: применяет отложенные вебхуки, переклеймивает застрявшие в
`processing` задачи (упавший воркер) и переставляет восстановимые заказы. Всё
идемпотентно — восстановление физически не может привести к двойной выдаче.

**Каталог под нагрузкой (Этап 5).** Остаток хранится денормализованным счётчиком
`stock.available` (а не `COUNT(*)` по кодам), поэтому цена строки не зависит от
объёма пула. Частичный индекс `products (type, sku) WHERE is_active` обслуживает
`WHERE is_active ORDER BY type, sku LIMIT N`: Postgres идёт по индексу по порядку
и останавливается после N строк — без сортировки и без full scan. Факт на ~5000
SKU:

```
Limit (actual time=0.008..0.129 rows=50)
  -> Nested Loop Left Join
       -> Index Scan using products_storefront_idx on products  (rows=50)
       -> Index Scan using stock_pkey on stock  (loops=50)
Execution Time: 0.156 ms
```

## Как масштабировали бы под нагрузку

- **Партиционирование** `orders`/`webhook_events`/`ledger_entries` по времени;
  холодные партиции — в архив.
- **Горизонтальное масштабирование воркеров** уже встроено: число воркеров
  выдачи/восстановления задаётся в `.env` (`DELIVERY_WORKER_COUNT` /
  `RECOVERY_WORKER_COUNT`) — они делят один stateless-набор сервисов и
  конкурентно разбирают очередь через `FOR UPDATE SKIP LOCKED` (один заказ не
  берут два воркера, двойной выдачи нет). Это же масштабируется и на несколько
  процессов/подов без изменений кода. При большом числе воркеров не забыть
  поднять размер пула БД (`POSTGRES.pool_max_size`).
- **Витрина остатков** под реальный трафик — кэш (Redis) с инвалидацией по
  событию `stock.changed`, либо материализованное представление; сама SQL-схема
  уже готова к этому.
- **Разнесение доменов**: сервис поставщиков вынесен отдельным процессом (в
  реальном мире — своя БД и свой деплой); платёжный инбокс можно вынести в
  брокер (Kafka/SQS) с тем же принципом дедупа по `event_id`.
- **Backpressure/ретраи** по выдаче — экспоненциальный бэкофф уже реализован в
  outbox; при устойчивых отказах поставщиков заказы безопасно «ждут» в
  восстановимом статусе.

---

## API (кратко)

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/orders` | создать заказ по `{"sku": "..."}` |
| `GET` | `/orders/{id}` | заказ (с кодом, если выдан) |
| `POST` | `/orders/{id}/redeliver` | ручной повтор выдачи (восстановление) |
| `POST` | `/webhook/payment` | вебхук платёжки (идемпотентный, вне порядка) |
| `GET` | `/catalog` | витрина остатков (пагинация `page`, `size`) |
| `GET` | `/catalog/{sku}` | карточка товара |
| `GET` | `/admin/reconcile` | сверка + баланс журнала |
| `POST` | `/admin/recover` | применить отложенные вебхуки и переставить зависшие заказы |

Сервис поставщиков (`:8002`): `POST /{A|B}/issue`, `POST /{A|B}/config`,
`GET /{A|B}/status`, `POST /{A|B}/reset?restock=true`.

---

## Структура

Слоение строгое: **вся SQL — только в repository**, в service — исключительно
бизнес-логика. Транзакции, охватывающие несколько запросов (exactly-once
переходы), реализованы через Unit-of-Work (`repository/postgresql/uow.py`):
service открывает границу транзакции и передаёт соединение в методы репозиториев,
а сами SQL-запросы живут в репозиториях.

```
app/                      # приложение-магазин (слои: routes → services → repository)
  internal/services/      # order/payment/delivery/reconcile/catalog — только бизнес-логика
  internal/workers/       # delivery_worker (очередь), recovery_worker (свипер)
  internal/repository/    # доступ к БД (asyncpg): вся SQL + uow.py (Unit of Work)
  pkg/clients/            # HTTP-клиент к поставщикам (классификация таймаут/ошибка)
  pkg/logger/events.py    # структурированные JSON-события
supplier/                 # заглушки поставщиков A/B (идемпотентность + инъекция отказов)
migrations/               # yoyo: схема + сид (каталог, 50 ключей, конфиг поставщиков)
scripts/emulate_payment.py# эмулятор платёжки + харнесс гонок
scripts/load_catalog.py   # Stage 5: нагрузка каталога + EXPLAIN
tests/                    # 9 тестов на все 6 критериев приёмки
```

---

## Время по факту

≈ 1 рабочий день (проектирование модели данных и инвариантов exactly-once,
реализация, заглушки поставщиков, тесты на критичных путях, Docker-обвязка).