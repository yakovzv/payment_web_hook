LOCAL_DSN ?= postgresql://shop:shop@localhost:5432/shop

help:
	@echo "make up        — собрать и поднять весь стек (postgres + migrate + app + suppliers)"
	@echo "make down      — остановить стек"
	@echo "make logs      — логи приложения (структурированные события платежей/выдачи)"
	@echo "make migrate   — применить миграции yoyo к локальной БД ($(LOCAL_DSN))"
	@echo "make test      — прогнать тесты (стек должен быть поднят: make up)"
	@echo "make race      — демо: заказ + 50 параллельных вебхуков + результат"
	@echo "make load      — Stage 5: залить тысячи SKU и показать план запроса витрины"
	@echo "make reconcile — отчёт сверки (оплачен-не-выдан / выдан-не-оплачен / баланс)"

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f app

migrate:
	uv run yoyo apply -b --database "$(LOCAL_DSN)" ./migrations

test:
	uv run --group dev pytest -v

race:
	uv run python scripts/emulate_payment.py demo --count 50

load:
	uv run python scripts/load_catalog.py --count 5000

reconcile:
	@curl -s http://localhost:8001/admin/reconcile | python -m json.tool