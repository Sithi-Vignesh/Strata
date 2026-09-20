"""TableScan execution operator bridging physical Table storage to logical Tuple streams."""

from typing import Iterator, Optional, Tuple as PyTuple

from strata_engine.catalog.table import Table
from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple
from strata_engine.storage.exceptions import StorageClosedError
from strata_engine.storage.record_id import RecordId


class TableScan(Operator):
    """Execution operator that scans a relational Table and produces a logical Tuple stream.

    Borrows an existing Table instance and yields schema-bound Tuple records,
    discarding physical RecordId identifiers.
    """

    __slots__ = ("_table", "_is_open", "_exhausted", "_iter")

    def __init__(self, table: Table) -> None:
        """Initialize TableScan with an open Table.

        Args:
            table: Table instance to scan.

        Raises:
            TypeError: If table is not an instance of Table.
        """
        if not isinstance(table, Table):
            raise TypeError(f"Expected Table instance, got {type(table).__name__}.")

        self._table: Table = table
        self._is_open: bool = False
        self._exhausted: bool = False
        self._iter: Optional[Iterator[PyTuple[RecordId, Tuple]]] = None

    @property
    def table(self) -> Table:
        """Return the underlying borrowed Table instance."""
        return self._table

    @property
    def schema(self) -> Schema:
        """Return the schema of the scanned table. Available before open()."""
        return self._table.schema

    @property
    def is_open(self) -> bool:
        """Return True if the scan operator is currently open."""
        return self._is_open

    def open(self) -> None:
        """Open or rewind the scan from the beginning of the table.

        Raises:
            StorageClosedError: If the underlying table is closed.
        """
        if self._table.is_closed:
            raise StorageClosedError(
                f"Cannot open TableScan on closed Table '{self._table.name}'."
            )

        if self._iter is not None and hasattr(self._iter, "close"):
            try:
                self._iter.close()
            except Exception:
                pass
        self._iter = None

        try:
            self._iter = self._table.scan()
            self._is_open = True
            self._exhausted = False
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def next(self) -> Optional[Tuple]:
        """Fetch the next logical Tuple from the table, or return None if exhausted.

        Raises:
            OperatorClosedError: If the scan is not currently open.
            StorageClosedError: If the underlying table was closed.
        """
        if not self.is_open:
            raise OperatorClosedError("TableScan is not open. Call open() first.")

        if self._exhausted:
            return None

        try:
            assert self._iter is not None
            _rid, tuple_obj = next(self._iter)
            return tuple_obj
        except StopIteration:
            self._exhausted = True
            return None
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def close(self) -> None:
        """Close this scan and release internal iterator resources.

        Never closes the underlying borrowed Table. Idempotent and exception-safe.
        """
        self._is_open = False
        self._exhausted = False
        if self._iter is not None:
            if hasattr(self._iter, "close"):
                try:
                    self._iter.close()
                except Exception:
                    pass
            self._iter = None

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        return f"TableScan(table='{self._table.name}', status='{status}')"
