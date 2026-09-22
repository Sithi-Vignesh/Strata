"""Blocking global aggregate execution operator and resolved specifications."""

from dataclasses import dataclass
from typing import Optional, Sequence

from strata_engine.execution.exceptions import ExecutionError, OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.schema.data_type import DataType
from strata_engine.schema.schema import Schema
from strata_engine.schema.serializer import INT64_MAX, INT64_MIN
from strata_engine.schema.tuple import Tuple


@dataclass(frozen=True, slots=True)
class ResolvedAggregate:
    """Execution-local aggregate definition resolved against an input schema."""

    operation: str
    column_index: int | None
    input_type: DataType | None

    def __post_init__(self) -> None:
        if self.operation not in {"COUNT", "SUM", "AVG", "MIN", "MAX"}:
            raise ValueError(f"Unsupported aggregate operation '{self.operation}'.")
        if self.column_index is not None and (
            type(self.column_index) is not int or self.column_index < 0
        ):
            raise ValueError("column_index must be a non-negative int or None.")
        if self.operation == "COUNT" and self.column_index is None:
            if self.input_type is not None:
                raise ValueError("COUNT(*) must not have an input type.")
        elif self.column_index is None or not isinstance(self.input_type, DataType):
            raise ValueError("Column aggregates require a source index and DataType.")


class Aggregate(Operator):
    """Compute global aggregate values incrementally while opening an owned child."""

    __slots__ = ("_child", "_aggregates", "_schema", "_result", "_is_open", "_exhausted")

    def __init__(
        self,
        child: Operator,
        aggregates: Sequence[ResolvedAggregate],
        schema: Schema,
    ) -> None:
        if not isinstance(child, Operator):
            raise TypeError(f"Expected Operator instance for child, got {type(child).__name__}.")
        if not isinstance(aggregates, Sequence) or isinstance(aggregates, (str, bytes)):
            raise TypeError("Expected sequence of ResolvedAggregate objects.")
        resolved = tuple(aggregates)
        if not resolved:
            raise ValueError("Aggregate requires at least one aggregate specification.")
        if not all(isinstance(item, ResolvedAggregate) for item in resolved):
            raise TypeError("Aggregate specifications must all be ResolvedAggregate instances.")
        if not isinstance(schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(schema).__name__}.")
        if len(schema) != len(resolved):
            raise ValueError("Aggregate output schema must contain one column per aggregate.")
        if any(item.column_index is not None and item.column_index >= child.schema.column_count for item in resolved):
            raise ValueError("Aggregate source column index is outside the child schema.")

        self._child = child
        self._aggregates = resolved
        self._schema = schema
        self._result: Tuple | None = None
        self._is_open = False
        self._exhausted = False

    @property
    def child(self) -> Operator:
        return self._child

    @property
    def aggregates(self) -> tuple[ResolvedAggregate, ...]:
        """Return the immutable execution-local aggregate definitions."""
        return self._aggregates

    @property
    def schema(self) -> Schema:
        return self._schema

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        """Open child, consume it, and publish one finalized aggregate tuple."""
        self._result = None
        self._is_open = False
        self._exhausted = False
        try:
            states = [_new_state(item) for item in self._aggregates]
            self._child.open()
            while (row := self._child.next()) is not None:
                for item, state in zip(self._aggregates, states):
                    _update_state(item, state, row)
            values = tuple(_finalize_state(item, state) for item, state in zip(self._aggregates, states))
            self._result = Tuple(values, schema=self._schema)
            self._is_open = True
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def next(self) -> Optional[Tuple]:
        if not self.is_open:
            raise OperatorClosedError("Aggregate is not open. Call open() first.")
        if self._exhausted:
            return None
        self._exhausted = True
        return self._result

    def close(self) -> None:
        self._result = None
        self._is_open = False
        self._exhausted = False
        try:
            self._child.close()
        except Exception:
            pass


def _new_state(item: ResolvedAggregate) -> dict[str, object]:
    if item.operation == "COUNT":
        return {"count": 0}
    if item.operation in {"SUM", "AVG"}:
        return {"total": 0.0 if item.input_type == DataType.FLOAT else 0, "count": 0}
    return {"value": None, "seen": False}


def _update_state(item: ResolvedAggregate, state: dict[str, object], row: Tuple) -> None:
    if item.operation == "COUNT" and item.column_index is None:
        state["count"] = int(state["count"]) + 1
        return

    assert item.column_index is not None
    value = row[item.column_index]
    if item.operation == "COUNT":
        if value is not None:
            state["count"] = int(state["count"]) + 1
        return
    if value is None:
        return
    if item.operation in {"SUM", "AVG"}:
        state["total"] = state["total"] + value  # type: ignore[operator]
        state["count"] = int(state["count"]) + 1
        return
    if not bool(state["seen"]):
        state["value"] = value
        state["seen"] = True
    elif item.operation == "MIN" and value < state["value"]:
        state["value"] = value
    elif item.operation == "MAX" and value > state["value"]:
        state["value"] = value


def _finalize_state(item: ResolvedAggregate, state: dict[str, object]) -> object:
    if item.operation == "COUNT":
        return _require_bigint(int(state["count"]), item.operation)
    if item.operation == "SUM":
        if int(state["count"]) == 0:
            return None
        total = state["total"]
        if item.input_type == DataType.FLOAT:
            return float(total)
        return _require_bigint(int(total), item.operation)
    if item.operation == "AVG":
        count = int(state["count"])
        return None if count == 0 else float(state["total"] / count)  # type: ignore[operator]
    return state["value"] if bool(state["seen"]) else None


def _require_bigint(value: int, operation: str) -> int:
    if not INT64_MIN <= value <= INT64_MAX:
        raise ExecutionError(
            f"{operation} result {value} is outside signed BIGINT range [{INT64_MIN}, {INT64_MAX}]."
        )
    return value
