from app.internal.repository.postgresql import Repositories
from app.internal.services import Services
from app.internal.utils import Utils
from app.internal.workers import Workers
from app.pkg.clients import Clients
from app.pkg.connectors import Connectors
from app.pkg.models.core.containers import Container, Containers

__all__ = ["__containers__"]


__containers__ = Containers(
    pkg_name=__name__,
    containers=[
        Container(container=Services),
        Container(container=Connectors),
        Container(container=Clients),
        Container(container=Workers),
        Container(container=Repositories),
        Container(container=Utils),
    ],
)

