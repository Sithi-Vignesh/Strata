"""Immutable name-based aggregate specifications."""

from dataclasses import dataclass


SUPPORTED_AGGREGATES = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX"})


@dataclass(frozen=True, slots=True)
class AggregateSpec:
    """One unresolved global aggregate request."""

    operation: str
    column_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str):
            raise TypeError(f"operation must be a str, got {type(self.operation).__name__}.")
        operation = self.operation.upper()
        if operation not in SUPPORTED_AGGREGATES:
            raise ValueError(f"Unsupported aggregate operation '{self.operation}'.")
        if self.column_name is not None and not isinstance(self.column_name, str):
            raise TypeError("column_name must be a str or None.")
        if operation == "COUNT":
            pass
        elif self.column_name is None:
            raise ValueError(f"{operation} requires a source column.")
        object.__setattr__(self, "operation", operation)
