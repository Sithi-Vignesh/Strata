"""Streaming LIMIT/OFFSET execution operator."""

from typing import Optional

from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple


class Limit(Operator):
    """Skip an offset then emit no more than a configured number of child rows."""

    __slots__ = ("_child", "_limit", "_offset", "_remaining_offset", "_emitted", "_is_open", "_exhausted")

    def __init__(self, child: Operator, limit: int, offset: int = 0) -> None:
        if not isinstance(child, Operator):
            raise TypeError(f"Expected Operator instance for child, got {type(child).__name__}.")
        _validate_count("limit", limit)
        _validate_count("offset", offset)
        self._child = child
        self._limit = limit
        self._offset = offset
        self._remaining_offset = offset
        self._emitted = 0
        self._is_open = False
        self._exhausted = False

    @property
    def child(self) -> Operator:
        return self._child

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def schema(self) -> Schema:
        return self._child.schema

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        """Open the child without consuming offset rows."""
        self._remaining_offset = self._offset
        self._emitted = 0
        self._is_open = False
        self._exhausted = False
        try:
            self._child.open()
            self._is_open = True
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def next(self) -> Optional[Tuple]:
        if not self.is_open:
            raise OperatorClosedError("Limit is not open. Call open() first.")
        if self._exhausted:
            return None
        try:
            if self._emitted == self._limit:
                self._exhausted = True
                return None
            while self._remaining_offset > 0:
                if self._child.next() is None:
                    self._exhausted = True
                    return None
                self._remaining_offset -= 1
            row = self._child.next()
            if row is None:
                self._exhausted = True
                return None
            self._emitted += 1
            return row
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def close(self) -> None:
        self._remaining_offset = self._offset
        self._emitted = 0
        self._is_open = False
        self._exhausted = False
        try:
            self._child.close()
        except Exception:
            pass


def _validate_count(name: str, value: int) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}.")
