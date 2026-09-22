"""Immutable resolved query intent accepted by the planner."""

from dataclasses import dataclass
from typing import Sequence

from strata_engine.catalog import Table
from strata_engine.execution import Predicate


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Already-resolved table, optional predicate, and optional projection intent."""

    table: Table
    predicate: Predicate | None = None
    projection: tuple[str, ...] | None = None

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
