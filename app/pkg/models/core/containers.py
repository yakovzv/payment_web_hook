from dataclasses import dataclass, field
from typing import Callable, List, Optional

from dependency_injector import containers
from fastapi import FastAPI

__all__ = ["Container", "Containers"]


@dataclass(frozen=True)
class Container:
    #: containers.Container: вызываемый объект декларативного контейнера dependency_injector.
    container: Callable[..., containers.Container]

    #: List[str]: Массив пакетов, для которых будет доступен инжектор.
    #  По умолчанию: ["app"]
    packages: List[str] = field(default_factory=lambda: ["app"])


@dataclass(frozen=True)
class Containers:
    #: str: __name__ основного пакета.
    pkg_name: str

    #: List[Container]: Список моделей `Container`.
    containers: List[Container]

    def wire_packages(
        self,
        app: Optional[FastAPI] = None,
        pkg_name: Optional[str] = None,
    ):
        pkg_name = pkg_name if pkg_name else self.pkg_name
        for container in self.containers:
            cont = container.container()
            cont.wire(packages=[pkg_name, *container.packages])
            if app:
                setattr(app, container.container.__name__.lower(), cont)
