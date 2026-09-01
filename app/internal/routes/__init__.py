from app.internal.pkg.models.routes import Routes
from app.internal.routes import admin, catalog, orders, webhook


__all__ = ["__routes__"]


__routes__ = Routes(
    routers=(
        catalog.router,
        orders.router,
        webhook.router,
        admin.router,
    ),
)