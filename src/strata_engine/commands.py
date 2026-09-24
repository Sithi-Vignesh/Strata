"""Resolved mutation commands executed by the public engine facade."""

from dataclasses import dataclass

from strata_engine.catalog import Table


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
