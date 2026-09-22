"""Immutable resolved query intent accepted by the planner."""

from dataclasses import dataclass
from typing import Sequence

from strata_engine.catalog import Table
from strata_engine.execution import Predicate
from strata_engine.planning.order_by import OrderBy


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Already-resolved table, optional predicate, and optional projection intent."""

    table: Table
    predicate: Predicate | None = None
    projection: tuple[str, ...] | None = None
    order_by: tuple[OrderBy, ...] | None = None
    limit: int | None = None
    offset: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.table, Table):
            raise TypeError(f"Expected Table instance, got {type(self.table).__name__}.")
        if self.predicate is not None and not isinstance(self.predicate, Predicate):
            raise TypeError(
                "Expected Predicate instance or None for predicate, "
                f"got {type(self.predicate).__name__}."
            )
        if self.projection is not None:
            if not isinstance(self.projection, Sequence) or isinstance(
                self.projection, (str, bytes)
            ):
                raise TypeError(
                    "Expected sequence of column names or None for projection, "
                    f"got {type(self.projection).__name__}."
                )
            object.__setattr__(self, "projection", tuple(self.projection))
        if self.order_by is not None:
            if not isinstance(self.order_by, Sequence) or isinstance(self.order_by, (str, bytes)):
                raise TypeError(
                    "Expected sequence of OrderBy objects or None for order_by, "
                    f"got {type(self.order_by).__name__}."
                )
            order_by = tuple(self.order_by)
            if not all(isinstance(item, OrderBy) for item in order_by):
                raise TypeError("Order-by items must all be OrderBy instances.")
            object.__setattr__(self, "order_by", order_by)
        if self.limit is not None:
            _validate_count("limit", self.limit)
        _validate_count("offset", self.offset)
        if self.limit is None and self.offset != 0:
            raise ValueError("offset requires a non-None limit.")


def _validate_count(name: str, value: int) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}.")
