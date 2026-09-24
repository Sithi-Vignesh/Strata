"""Plan for global aggregation over one child plan."""

from collections.abc import Sequence

from strata_engine.execution.aggregate import Aggregate, ResolvedAggregate, ResolvedAggregateOutput
from strata_engine.planning.aggregate import AggregateOutputSpec, AggregateSpec
from strata_engine.planning.plan import Plan
from strata_engine.schema import Column, DataType, DuplicateColumnError, Schema, TypeMismatchError


class AggregatePlan(Plan):
    """Resolve global aggregate specifications and create fresh Aggregate operators."""

    __slots__ = ("_child", "_aggregates", "_group_by", "_resolved", "_group_indexes", "_output_layout", "_schema")

    def __init__(self, child: Plan, aggregates: Sequence[AggregateSpec], group_by: Sequence[str] | None = None,
                 output_layout: Sequence[AggregateOutputSpec] | None = None) -> None:
        if not isinstance(child, Plan):
            raise TypeError(f"Expected Plan instance for child, got {type(child).__name__}.")
        if not isinstance(aggregates, Sequence) or isinstance(aggregates, (str, bytes)):
            raise TypeError("Expected sequence of AggregateSpec objects.")
        specs = tuple(aggregates)
        if not specs:
            raise ValueError("AggregatePlan requires at least one aggregate specification.")
        if not all(isinstance(spec, AggregateSpec) for spec in specs):
            raise TypeError("Aggregate specifications must all be AggregateSpec instances.")

        seen: set[tuple[str, int | None]] = set()
        resolved: list[ResolvedAggregate] = []
        columns: list[Column] = []
        for spec in specs:
            source = None
            source_index = None
            if spec.column_name is not None:
                source_index = child.schema.column_index(spec.column_name)
                source = child.schema.get_column(source_index)
            key = (spec.operation, source_index)
            if key in seen:
                arg = "*" if source is None else source.name
                raise DuplicateColumnError(f"Duplicate aggregate specification {spec.operation}({arg}).")
            seen.add(key)
            _validate_spec(spec, source)
            output_type, nullable = _output_type(spec.operation, source)
            output_name = _output_name(spec.operation, source)
            max_length = source.max_length if output_type == DataType.VARCHAR and source is not None else None
            columns.append(Column(output_name, output_type, nullable=nullable, max_length=max_length))
            resolved.append(ResolvedAggregate(spec.operation, source_index, source.data_type if source else None))

        if group_by is not None and (not isinstance(group_by, Sequence) or isinstance(group_by, (str, bytes))):
            raise TypeError("Expected sequence of grouping column names or None for group_by.")
        groups = tuple(group_by or ())
        if not all(isinstance(name, str) for name in groups):
            raise TypeError("Grouping column names must be strings.")
        if len({name.lower() for name in groups}) != len(groups):
            raise DuplicateColumnError("Duplicate grouping column name.")
        group_indexes = tuple(child.schema.column_index(name) for name in groups)
        group_columns = tuple(child.schema.get_column(index) for index in group_indexes)
        layout_specs = tuple(output_layout) if output_layout is not None else tuple(
            AggregateOutputSpec("AGGREGATE", index) for index in range(len(resolved))
        )
        if not layout_specs or not all(isinstance(item, AggregateOutputSpec) for item in layout_specs):
            raise TypeError("Aggregate output layout must contain AggregateOutputSpec values.")
        if any(item.kind == "GROUP" and item.index >= len(groups) for item in layout_specs) or any(item.kind == "AGGREGATE" and item.index >= len(resolved) for item in layout_specs):
            raise ValueError("Aggregate output layout index is outside its source collection.")
        aggregate_columns = tuple(columns)
        columns = [group_columns[item.index] if item.kind == "GROUP" else aggregate_columns[item.index] for item in layout_specs]
        self._child = child
        self._aggregates = specs
        self._group_by = groups
        self._resolved = tuple(resolved)
        self._group_indexes = group_indexes
        self._output_layout = tuple(ResolvedAggregateOutput(item.kind, item.index) for item in layout_specs)
        self._schema = Schema(columns)
        self._freeze()

    @property
    def child(self) -> Plan:
        return self._child

    @property
    def aggregates(self) -> tuple[AggregateSpec, ...]:
        return self._aggregates

    @property
    def group_by(self) -> tuple[str, ...]:
        return self._group_by

    @property
    def group_indexes(self) -> tuple[int, ...]:
        return self._group_indexes

    @property
    def schema(self) -> Schema:
        return self._schema

    def create_operator(self) -> Aggregate:
        return Aggregate(self._child.create_operator(), self._resolved, self._schema, self._group_indexes, self._output_layout)


def _validate_spec(spec: AggregateSpec, source: Column | None) -> None:
    if spec.operation == "COUNT":
        return
    if source is None:
        raise ValueError(f"{spec.operation} requires a source column.")
    if spec.operation in {"SUM", "AVG"} and source.data_type not in {
        DataType.INTEGER,
        DataType.BIGINT,
        DataType.FLOAT,
    }:
        raise TypeMismatchError(
            f"{spec.operation} requires INTEGER, BIGINT, or FLOAT, got {source.data_type.value}."
        )


def _output_type(operation: str, source: Column | None) -> tuple[DataType, bool]:
    if operation == "COUNT":
        return DataType.BIGINT, False
    assert source is not None
    if operation == "SUM":
        return (DataType.FLOAT if source.data_type == DataType.FLOAT else DataType.BIGINT), True
    if operation == "AVG":
        return DataType.FLOAT, True
    return source.data_type, True


def _output_name(operation: str, source: Column | None) -> str:
    if source is None:
        return "count_star"
    prefix = operation.lower() + "_"
    return prefix + source.name[: 64 - len(prefix)]
