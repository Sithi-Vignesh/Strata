"""Resolved mutation commands executed by the public engine facade."""

from dataclasses import dataclass

from strata_engine.catalog import Table
from strata_engine.execution import Predicate
from strata_engine.schema import Schema


@dataclass(frozen=True, slots=True)
class InsertCommand:
    """A resolved single-row insertion target and ordered literal values."""

    table: Table
    values: tuple[object | None, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.table, Table):
            raise TypeError(f"Expected Table instance, got {type(self.table).__name__}.")
        if not isinstance(self.values, tuple):
            raise TypeError(f"Expected tuple of SQL literal values, got {type(self.values).__name__}.")


@dataclass(frozen=True, slots=True)
class CreateTableCommand:
    """Resolved CREATE TABLE target and schema, ready for engine dispatch."""

    table_name: str
    schema: Schema

    def __post_init__(self) -> None:
        if not isinstance(self.table_name, str):
            raise TypeError(f"Expected table name str, got {type(self.table_name).__name__}.")
        if not isinstance(self.schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(self.schema).__name__}.")


@dataclass(frozen=True, slots=True)
class DropTableCommand:
    """Resolved DROP TABLE target, ready for engine dispatch."""

    table_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.table_name, str):
            raise TypeError(f"Expected table name str, got {type(self.table_name).__name__}.")


@dataclass(frozen=True, slots=True)
class DeleteCommand:
    """Resolved DELETE target and optional bound predicate."""

    table: Table
    predicate: Predicate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.table, Table):
            raise TypeError(f"Expected Table instance, got {type(self.table).__name__}.")
        if self.predicate is not None and not isinstance(self.predicate, Predicate):
            raise TypeError(
                "Expected Predicate instance or None for predicate, "
                f"got {type(self.predicate).__name__}."
            )


@dataclass(frozen=True, slots=True)
class BoundUpdateAssignment:
    """One resolved UPDATE assignment with its schema ordinal."""

    column_index: int
    value: object | None

    def __post_init__(self) -> None:
        if type(self.column_index) is not int or self.column_index < 0:
            raise ValueError("column_index must be a non-negative integer.")


@dataclass(frozen=True, slots=True)
class UpdateCommand:
    """Resolved literal-only UPDATE target, assignments, and optional predicate."""

    table: Table
    assignments: tuple[BoundUpdateAssignment, ...]
    predicate: Predicate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.table, Table):
            raise TypeError(f"Expected Table instance, got {type(self.table).__name__}.")
        if not isinstance(self.assignments, tuple) or not self.assignments:
            raise ValueError("assignments must be a non-empty tuple.")
        if not all(isinstance(item, BoundUpdateAssignment) for item in self.assignments):
            raise TypeError("assignments must contain BoundUpdateAssignment values.")
        if self.predicate is not None and not isinstance(self.predicate, Predicate):
            raise TypeError("predicate must be a Predicate or None.")
