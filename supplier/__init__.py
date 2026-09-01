"""Заглушки двух поставщиков (A и B) за префиксами /A и /B: выдают коды,
идемпотентны по request_id, умеют падать и висеть по настройке."""

from fastapi import FastAPI

from supplier.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Supplier Stubs (A/B)")
    app.include_router(router)
    return app


application = create_app()