"""Resolved mutation commands executed by the public engine facade."""

from dataclasses import dataclass

from strata_engine.catalog import Table
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
