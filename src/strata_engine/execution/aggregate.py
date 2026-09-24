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


@dataclass(frozen=True, slots=True)
class ResolvedAggregateOutput:
    """Execution-local reference to a grouping key or aggregate result."""

    kind: str
    index: int

    def __post_init__(self) -> None:
        if self.kind not in {"GROUP", "AGGREGATE"}:
            raise ValueError("Aggregate output kind must be GROUP or AGGREGATE.")
        if type(self.index) is not int or self.index < 0:
            raise ValueError("Aggregate output index must be a non-negative int.")


class Aggregate(Operator):
    """Compute global aggregate values incrementally while opening an owned child."""

    __slots__ = ("_child", "_aggregates", "_group_indexes", "_output_layout", "_schema", "_results", "_position", "_is_open", "_exhausted")

    def __init__(
        self,
        child: Operator,
        aggregates: Sequence[ResolvedAggregate],
        schema: Schema,
        group_indexes: Sequence[int] = (),
        output_layout: Sequence[ResolvedAggregateOutput] | None = None,
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
        if any(item.column_index is not None and item.column_index >= child.schema.column_count for item in resolved):
            raise ValueError("Aggregate source column index is outside the child schema.")

        groups = tuple(group_indexes)
        if not all(type(index) is int and 0 <= index < child.schema.column_count for index in groups):
            raise ValueError("Aggregate grouping index is outside the child schema.")
        layout = tuple(output_layout) if output_layout is not None else tuple(
            ResolvedAggregateOutput("AGGREGATE", index) for index in range(len(resolved))
        )
        if not layout or not all(isinstance(item, ResolvedAggregateOutput) for item in layout):
            raise TypeError("Aggregate output layout must contain ResolvedAggregateOutput values.")
        if len(schema) != len(layout):
            raise ValueError("Aggregate output schema must match its output layout.")
        if any(item.kind == "GROUP" and item.index >= len(groups) for item in layout) or any(item.kind == "AGGREGATE" and item.index >= len(resolved) for item in layout):
            raise ValueError("Aggregate output layout index is outside its source collection.")
        self._child = child
        self._aggregates = resolved
        self._group_indexes = groups
        self._output_layout = layout
        self._schema = schema
        self._results: list[Tuple] = []
        self._position = 0
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
    def group_indexes(self) -> tuple[int, ...]:
        """Return physical child indexes forming each grouping key."""
        return self._group_indexes

    @property
    def output_layout(self) -> tuple[ResolvedAggregateOutput, ...]:
        """Return the resolved layout used to construct each output tuple."""
        return self._output_layout

    @property
    def schema(self) -> Schema:
        return self._schema

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        """Open child, consume it, and publish finalized global or grouped tuples."""
        self._results.clear()
        self._position = 0
        self._is_open = False
        self._exhausted = False
        try:
            groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
            if not self._group_indexes:
                groups[()] = [_new_state(item) for item in self._aggregates]
            self._child.open()
            while (row := self._child.next()) is not None:
                key = tuple(row[index] for index in self._group_indexes)
                states = groups.get(key)
                if states is None:
                    states = [_new_state(item) for item in self._aggregates]
                    groups[key] = states
                for item, state in zip(self._aggregates, states):
                    _update_state(item, state, row)
            for key, states in groups.items():
                aggregate_values = tuple(_finalize_state(item, state) for item, state in zip(self._aggregates, states))
                values = tuple(key[item.index] if item.kind == "GROUP" else aggregate_values[item.index] for item in self._output_layout)
                self._results.append(Tuple(values, schema=self._schema))
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
        if self._position >= len(self._results):
            self._exhausted = True
            return None
        result = self._results[self._position]
        self._position += 1
        return result

    def close(self) -> None:
        self._results.clear()
        self._position = 0
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
