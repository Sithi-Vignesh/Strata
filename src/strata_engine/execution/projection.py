"""Projection execution operator selecting and reordering columns from a child stream."""

from typing import Optional, Sequence

from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema.column import Column
from strata_engine.schema.exceptions import DuplicateColumnError
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple

MIN_PROJECTION_COLUMNS = 1
MAX_PROJECTION_COLUMNS = 256


class Projection(Operator):
    """Execution operator that projects a subset and order of columns from a child operator.

    Produces new schema-bound Tuple instances with an output Schema derived from
    the requested columns.
    """

    __slots__ = ("_child", "_output_schema", "_proj_indices", "_is_open", "_exhausted")

    def __init__(self, child: Operator, columns: Sequence[str]) -> None:
        """Initialize Projection operator with child operator and target column names.

        Args:
            child: Source Operator producing tuples.
            columns: Sequence of column names to project in desired ordinal order.

        Raises:
            TypeError: If child is not an Operator or columns is not a sequence of strings.
            ValueError: If columns length is not between 1 and 256.
            ColumnNotFoundError: If a requested column does not exist in child schema.
            DuplicateColumnError: If columns contains duplicate case-insensitive names.
        """
        if not isinstance(child, Operator):
            raise TypeError(f"Expected Operator instance for child, got {type(child).__name__}.")
        if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes)):
            raise TypeError(
                f"Expected sequence of column names, got {type(columns).__name__}."
            )

        col_count = len(columns)
        if not (MIN_PROJECTION_COLUMNS <= col_count <= MAX_PROJECTION_COLUMNS):
            raise ValueError(
                f"Projection must contain between {MIN_PROJECTION_COLUMNS} and "
                f"{MAX_PROJECTION_COLUMNS} columns, got {col_count}."
            )

        seen_names: set[str] = set()
        resolved_cols: list[Column] = []
        indices: list[int] = []

        for col_name in columns:
            if not isinstance(col_name, str):
                raise TypeError(
                    f"Projected column name must be str, got {type(col_name).__name__}."
                )

            lower = col_name.lower()
            if lower in seen_names:
                raise DuplicateColumnError(
                    f"Duplicate projected column name '{col_name}' (matches case-insensitively)."
                )
            seen_names.add(lower)

            # Resolves Column object from child schema; raises ColumnNotFoundError if missing
            col_obj = child.schema.get_column_by_name(col_name)
            resolved_cols.append(col_obj)
            indices.append(child.schema.column_index(col_name))

        self._child: Operator = child
        self._output_schema: Schema = Schema(resolved_cols)
        self._proj_indices: tuple[int, ...] = tuple(indices)
        self._is_open: bool = False
        self._exhausted: bool = False

    @property
    def child(self) -> Operator:
        """Return the owned child operator."""
        return self._child

    @property
    def schema(self) -> Schema:
        """Return the output Schema of tuples produced by this projection."""
        return self._output_schema

    @property
    def is_open(self) -> bool:
        """Return True if this projection is open."""
        return self._is_open

    def open(self) -> None:
        """Open or rewind this projection and its child operator."""
        try:
            self._child.open()
            self._is_open = True
            self._exhausted = False
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def next(self) -> Optional[Tuple]:
        """Fetch the next projected Tuple, or return None if stream is exhausted.

        Raises:
            OperatorClosedError: If projection is not currently open.
        """
        if not self.is_open:
            raise OperatorClosedError("Projection is not open. Call open() first.")

        if self._exhausted:
            return None

        try:
            child_row = self._child.next()
            if child_row is None:
                self._exhausted = True
                return None

            values = tuple(child_row[idx] for idx in self._proj_indices)
            return Tuple(values, schema=self._output_schema)
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def close(self) -> None:
        """Close this projection and cascade closure to the child operator.

        Idempotent and exception-safe.
        """
        self._is_open = False
        self._exhausted = False
        try:
            self._child.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        cols_repr = ", ".join(self._output_schema.column_names)
        return f"Projection(child={self._child!r}, columns=[{cols_repr}], status='{status}')"
