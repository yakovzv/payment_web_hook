"""Все enum внутри моделей должны наследоваться от `BaseEnum`"""

from enum import Enum

__all__ = ["BaseEnum"]


class BaseEnum(Enum):
    """Базовая ENUM-модель."""

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return str(self.value)
