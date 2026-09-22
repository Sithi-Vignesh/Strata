"""Blocking in-memory sort operator and resolved execution sort keys."""

from dataclasses import dataclass
from typing import Optional, Sequence

from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple


@dataclass(frozen=True, slots=True)
class SortKey:
    """An execution-local, schema-resolved sort key."""

    column_index: int
    descending: bool = False

    def __post_init__(self) -> None:
        if type(self.column_index) is not int:
            raise TypeError(
                f"column_index must be an int, got {type(self.column_index).__name__}."
            )
        if self.column_index < 0:
            raise ValueError(f"column_index must be non-negative, got {self.column_index}.")
        if type(self.descending) is not bool:
            raise TypeError(
                f"descending must be a bool, got {type(self.descending).__name__}."
            )


class Sort(Operator):
    """Blocking operator that materializes and stably sorts all child rows on open."""

    __slots__ = ("_child", "_sort_keys", "_rows", "_position", "_is_open", "_exhausted")

    def __init__(self, child: Operator, sort_keys: Sequence[SortKey]) -> None:
        if not isinstance(child, Operator):
            raise TypeError(f"Expected Operator instance for child, got {type(child).__name__}.")
        if not isinstance(sort_keys, Sequence) or isinstance(sort_keys, (str, bytes)):
            raise TypeError(f"Expected sequence of SortKey objects, got {type(sort_keys).__name__}.")

        keys = tuple(sort_keys)
        if not keys:
            raise ValueError("Sort requires at least one sort key.")
        if not all(isinstance(key, SortKey) for key in keys):
            raise TypeError("Sort keys must all be SortKey instances.")
        if any(key.column_index >= child.schema.column_count for key in keys):
            raise ValueError("Sort key column index is outside the child schema.")

        self._child = child
        self._sort_keys = keys
        self._rows: list[Tuple] = []
        self._position = 0
        self._is_open = False
        self._exhausted = False

    @property
    def child(self) -> Operator:
        """Return the owned child operator."""
        return self._child

    @property
    def sort_keys(self) -> tuple[SortKey, ...]:
        """Return the immutable resolved sort specification."""
        return self._sort_keys

    @property
    def schema(self) -> Schema:
        """Return exactly the child schema."""
        return self._child.schema

    @property
    def is_open(self) -> bool:
        """Return whether this operator is open."""
        return self._is_open

    def open(self) -> None:
        """Open, materialize, and stably sort the child stream."""
        self._rows.clear()
        self._position = 0
        self._is_open = False
        self._exhausted = False
        try:
            self._child.open()
            while (row := self._child.next()) is not None:
                self._rows.append(row)
            for key in reversed(self._sort_keys):
                self._rows.sort(
                    key=lambda row, index=key.column_index: (row[index] is None, row[index]),
                    reverse=key.descending,
                )
            self._is_open = True
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def next(self) -> Optional[Tuple]:
        """Return the next sorted row, or EOF after the materialized rows."""
        if not self.is_open:
            raise OperatorClosedError("Sort is not open. Call open() first.")
        if self._exhausted:
            return None
        if self._position >= len(self._rows):
            self._exhausted = True
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def close(self) -> None:
        """Clear materialized rows and close the owned child operator."""
        self._rows.clear()
        self._position = 0
        self._is_open = False
        self._exhausted = False
        try:
            self._child.close()
        except Exception:
            pass

