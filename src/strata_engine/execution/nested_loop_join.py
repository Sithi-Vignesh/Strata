"""Incremental classic nested-loop INNER equality join."""
from dataclasses import dataclass
from typing import Optional
from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema import Schema, Tuple

@dataclass(frozen=True, slots=True)
class JoinKey:
    left_index: int
    right_index: int

    def __post_init__(self) -> None:
        if type(self.left_index) is not int or type(self.right_index) is not int:
            raise TypeError("Join key indexes must be ints.")
        if self.left_index < 0 or self.right_index < 0:
            raise ValueError("Join key indexes must be non-negative.")

class NestedLoopJoin(Operator):
    __slots__ = ("_left", "_right", "_key", "_schema", "_current_left", "_right_ready", "_is_open", "_exhausted")
    def __init__(self, left: Operator, right: Operator, key: JoinKey, schema: Schema) -> None:
        if not isinstance(left, Operator) or not isinstance(right, Operator):
            raise TypeError("NestedLoopJoin children must be Operators.")
        if not isinstance(key, JoinKey) or not isinstance(schema, Schema):
            raise TypeError("NestedLoopJoin requires JoinKey and Schema.")
        if key.left_index < 0 or key.left_index >= left.schema.column_count or key.right_index < 0 or key.right_index >= right.schema.column_count:
            raise ValueError("Join key index is outside child schema.")
        if schema.column_count != left.schema.column_count + right.schema.column_count:
            raise ValueError("Joined schema must contain all left then right columns.")
        self._left, self._right, self._key, self._schema = left, right, key, schema
        self._current_left = None; self._right_ready = False; self._is_open = False; self._exhausted = False
    @property
    def left(self) -> Operator: return self._left
    @property
    def right(self) -> Operator: return self._right
    @property
    def schema(self) -> Schema: return self._schema
    @property
    def is_open(self) -> bool: return self._is_open
    def open(self) -> None:
        self._current_left = None; self._right_ready = False; self._is_open = False; self._exhausted = False
        try:
            self._left.open(); self._right.open(); self._right_ready = True; self._is_open = True
        except Exception:
            try: self.close()
            except Exception: pass
            raise
    def next(self) -> Optional[Tuple]:
        if not self._is_open: raise OperatorClosedError("NestedLoopJoin is not open. Call open() first.")
        if self._exhausted: return None
        try:
            while True:
                if self._current_left is None:
                    self._current_left = self._left.next()
                    if self._current_left is None:
                        self._exhausted = True; return None
                    if not self._right_ready:
                        self._right.open(); self._right_ready = True
                right_row = self._right.next()
                if right_row is None:
                    self._current_left = None; self._right_ready = False; continue
                left_value = self._current_left[self._key.left_index]
                right_value = right_row[self._key.right_index]
                if left_value is not None and right_value is not None and left_value == right_value:
                    return Tuple(self._current_left.values + right_row.values, self._schema)
        except Exception:
            try: self.close()
            except Exception: pass
            raise
    def close(self) -> None:
        self._current_left = None; self._right_ready = False; self._is_open = False; self._exhausted = False
        for child in (self._left, self._right):
            try: child.close()
            except Exception: pass
