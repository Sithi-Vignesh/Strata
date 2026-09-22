"""Plan for scanning an already-resolved table."""

from strata_engine.catalog import Table
from strata_engine.execution import TableScan
from strata_engine.schema import Schema
from strata_engine.planning.plan import Plan


class TableScanPlan(Plan):
    """Immutable plan that borrows a resolved table and creates table scans."""

    __slots__ = ("_table",)

    def __init__(self, table: Table) -> None:
        if not isinstance(table, Table):
            raise TypeError(f"Expected Table instance, got {type(table).__name__}.")
        self._table = table
        self._freeze()

    @property
    def table(self) -> Table:
        """Return the borrowed resolved table."""
        return self._table

    @property
    def schema(self) -> Schema:
        """Return exactly the table schema."""
        return self._table.schema

    def create_operator(self) -> TableScan:
        """Create a fresh TableScan borrowing this plan's table."""
        return TableScan(self._table)
