"""Public materialized result values returned by the engine facade."""

from dataclasses import dataclass

from strata_engine.schema import Schema, Tuple


@dataclass(frozen=True, slots=True)
class QueryResult:
    """An immutable, fully materialized relational query result."""

    schema: Schema
    rows: tuple[Tuple, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(self.schema).__name__}.")
        if not isinstance(self.rows, tuple):
            raise TypeError(f"Expected tuple of Tuple rows, got {type(self.rows).__name__}.")
        for row in self.rows:
            if not isinstance(row, Tuple):
                raise TypeError(f"QueryResult rows must be Tuple instances, got {type(row).__name__}.")
            if row.schema != self.schema:
                raise ValueError("QueryResult row schema must match the result schema.")
