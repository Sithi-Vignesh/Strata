"""Index-backed Volcano scan operator for one table comparison condition."""

from typing import Optional

from strata_engine.catalog.index import TableIndex
from strata_engine.catalog.table import Table
from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple
from strata_engine.storage.exceptions import StorageClosedError
from strata_engine.storage.record_id import RecordId


_INDEX_SCAN_OPERATORS = ("=", "<", "<=", ">", ">=")


class IndexScan(Operator):
    """Borrow a table and one attached B+ tree to stream selected tuples.

    The scan owns only its per-execution RecordId snapshot.  The table owns the
    attached tree and remains responsible for its lifecycle.
    """

    __slots__ = (
        "_table", "_index", "_op", "_literal", "_is_open", "_exhausted",
        "_record_ids", "_position", "_tree_pages_visited",
        "_leaf_entries_examined", "_rids_selected", "_rows_fetched",
    )

    def __init__(self, table: Table, index: TableIndex, op: str, literal: object) -> None:
        if not isinstance(table, Table):
            raise TypeError(f"Expected Table instance, got {type(table).__name__}.")
        if not isinstance(index, TableIndex):
            raise TypeError(f"Expected TableIndex instance, got {type(index).__name__}.")
        if not isinstance(op, str):
            raise TypeError(f"op must be a str, got {type(op).__name__}.")
        if op not in _INDEX_SCAN_OPERATORS:
            raise ValueError(f"Unsupported index scan operator '{op}'.")
        if literal is None:
            raise ValueError("IndexScan literal cannot be None.")
        if index not in table.indexes:
            raise ValueError("IndexScan index must be attached to the supplied Table.")
        if index.column_ordinal < 0 or index.column_ordinal >= table.schema.column_count:
            raise ValueError("IndexScan index column ordinal is outside the table schema.")
        if table.schema[index.column_ordinal].data_type != index.key_type:
            raise ValueError("IndexScan index key type does not match the table schema.")

        self._table = table
        self._index = index
        self._op = op
        self._literal = literal
        self._is_open = False
        self._exhausted = False
        self._record_ids: tuple[RecordId, ...] = ()
        self._position = 0
        self._tree_pages_visited = 0
        self._leaf_entries_examined = 0
        self._rids_selected = 0
        self._rows_fetched = 0

    @property
    def table(self) -> Table:
        """Return the borrowed table."""
        return self._table

    @property
    def index(self) -> TableIndex:
        """Return the borrowed attached index binding."""
        return self._index

    @property
    def op(self) -> str:
        """Return the selected comparison operator."""
        return self._op

    @property
    def literal(self) -> object:
        """Return the selected comparison literal."""
        return self._literal

    @property
    def schema(self) -> Schema:
        return self._table.schema

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def tree_pages_visited(self) -> int:
        return self._tree_pages_visited

    @property
    def leaf_entries_examined(self) -> int:
        return self._leaf_entries_examined

    @property
    def rids_selected(self) -> int:
        return self._rids_selected

    @property
    def rows_fetched(self) -> int:
        return self._rows_fetched

    def open(self) -> None:
        """Perform one index lookup and reset this scan's execution state."""
        if self._table.is_closed:
            raise StorageClosedError(
                f"Cannot open IndexScan on closed Table '{self._table.name}'."
            )

        self._is_open = False
        self._exhausted = False
        self._record_ids = ()
        self._position = 0
        self._tree_pages_visited = 0
        self._leaf_entries_examined = 0
        self._rids_selected = 0
        self._rows_fetched = 0
        try:
            if self._op == "=":
                record_ids = self._index.tree.search(self._literal)
            elif self._op == "<":
                entries = self._index.tree.scan_range(upper=self._literal, upper_inclusive=False)
                record_ids = tuple(record_id for _key, record_id in entries)
            elif self._op == "<=":
                entries = self._index.tree.scan_range(upper=self._literal, upper_inclusive=True)
                record_ids = tuple(record_id for _key, record_id in entries)
            elif self._op == ">":
                entries = self._index.tree.scan_range(lower=self._literal, lower_inclusive=False)
                record_ids = tuple(record_id for _key, record_id in entries)
            else:
                entries = self._index.tree.scan_range(lower=self._literal, lower_inclusive=True)
                record_ids = tuple(record_id for _key, record_id in entries)
            stats = self._index.tree.last_operation_stats
            self._tree_pages_visited = stats.tree_pages_visited
            self._leaf_entries_examined = stats.leaf_entries_examined
            self._rids_selected = len(record_ids)
            self._record_ids = tuple(sorted(record_ids, key=lambda rid: (int(rid.page_id), rid.slot_id)))
            self._is_open = True
        except Exception:
            self.close()
            raise

    def next(self) -> Optional[Tuple]:
        """Fetch the next tuple selected by the index, or ``None`` at EOF."""
        if not self.is_open:
            raise OperatorClosedError("IndexScan is not open. Call open() first.")
        if self._exhausted:
            return None
        try:
            if self._position >= len(self._record_ids):
                self._exhausted = True
                return None
            record_id = self._record_ids[self._position]
            self._position += 1
            row = self._table.get(record_id)
            self._rows_fetched += 1
            return row
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Release local state without closing the borrowed table or tree."""
        self._is_open = False
        self._exhausted = False
        self._record_ids = ()
        self._position = 0

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        return (
            f"IndexScan(table='{self._table.name}', index='{self._index.name}', "
            f"op='{self._op}', literal={self._literal!r}, status='{status}')"
        )
