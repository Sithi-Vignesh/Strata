"""Immutable plan for one deterministic B+ tree access path."""

from strata_engine.catalog.index import TableIndex
from strata_engine.catalog.table import Table
from strata_engine.execution import IndexScan
from strata_engine.planning.plan import Plan
from strata_engine.schema import Schema


class IndexScanPlan(Plan):
    """Borrow a table/index binding and create fresh index scan operators."""

    __slots__ = ("_table", "_index", "_op", "_literal")

    def __init__(self, table: Table, index: TableIndex, op: str, literal: object) -> None:
        if not isinstance(table, Table):
            raise TypeError(f"Expected Table instance, got {type(table).__name__}.")
        if not isinstance(index, TableIndex):
            raise TypeError(f"Expected TableIndex instance, got {type(index).__name__}.")
        self._table = table
        self._index = index
        self._op = op
        self._literal = literal
        self._freeze()

    @property
    def table(self) -> Table:
        return self._table

    @property
    def index(self) -> TableIndex:
        return self._index

    @property
    def op(self) -> str:
        return self._op

    @property
    def literal(self) -> object:
        return self._literal

    @property
    def schema(self) -> Schema:
        return self._table.schema

    def create_operator(self) -> IndexScan:
        return IndexScan(self._table, self._index, self._op, self._literal)
