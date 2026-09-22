"""Execution projection by resolved indexes for join result labels."""
from typing import Optional, Sequence
from strata_engine.execution.exceptions import OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema import Schema, Tuple

class JoinProjection(Operator):
    __slots__ = ("_child", "_indices", "_schema", "_is_open", "_exhausted")
    def __init__(self, child: Operator, indices: Sequence[int], schema: Schema) -> None:
        if not isinstance(child, Operator) or not isinstance(schema, Schema): raise TypeError("JoinProjection requires Operator and Schema.")
        self._indices = tuple(indices)
        if not self._indices or len(self._indices) != len(schema) or any(type(i) is not int or i < 0 or i >= child.schema.column_count for i in self._indices): raise ValueError("Invalid join projection indexes.")
        self._child, self._schema, self._is_open, self._exhausted = child, schema, False, False
    @property
    def child(self): return self._child
    @property
    def schema(self): return self._schema
    @property
    def is_open(self): return self._is_open
    def open(self):
        self._is_open = False; self._exhausted = False
        try: self._child.open(); self._is_open = True
        except Exception:
            try: self.close()
            except Exception: pass
            raise
    def next(self) -> Optional[Tuple]:
        if not self._is_open: raise OperatorClosedError("JoinProjection is not open. Call open() first.")
        if self._exhausted: return None
        try:
            row = self._child.next()
            if row is None: self._exhausted = True; return None
            return Tuple(tuple(row[i] for i in self._indices), self._schema)
        except Exception:
            try: self.close()
            except Exception: pass
            raise
    def close(self):
        self._is_open = False; self._exhausted = False
        try: self._child.close()
        except Exception: pass
