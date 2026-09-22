"""Base class for immutable query plans."""

from abc import ABC, abstractmethod

from strata_engine.execution import Operator
from strata_engine.schema import Schema


class Plan(ABC):
    """Reusable, immutable description capable of creating an operator tree."""

    __slots__ = ("_frozen",)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(f"{type(self).__name__} instances are immutable.")
        object.__setattr__(self, name, value)

    def _freeze(self) -> None:
        """Prevent further mutation once subclass construction has completed."""
        object.__setattr__(self, "_frozen", True)

    @property
    @abstractmethod
    def schema(self) -> Schema:
        """Return the immutable schema produced by this plan."""

    @abstractmethod
    def create_operator(self) -> Operator:
        """Create a fresh, unopened execution-operator tree."""
