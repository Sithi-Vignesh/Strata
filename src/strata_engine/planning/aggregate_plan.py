"""Plan for global aggregation over one child plan."""

from collections.abc import Sequence

from strata_engine.execution.aggregate import Aggregate, ResolvedAggregate
from strata_engine.planning.aggregate import AggregateSpec
from strata_engine.planning.plan import Plan
from strata_engine.schema import Column, DataType, DuplicateColumnError, Schema, TypeMismatchError


class AggregatePlan(Plan):
    """Resolve global aggregate specifications and create fresh Aggregate operators."""

    __slots__ = ("_child", "_aggregates", "_resolved", "_schema")

    def __init__(self, child: Plan, aggregates: Sequence[AggregateSpec]) -> None:
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

        self._child = child
        self._aggregates = specs
        self._resolved = tuple(resolved)
        self._schema = Schema(columns)
        self._freeze()

    @property
    def child(self) -> Plan:
        return self._child

    @property
    def aggregates(self) -> tuple[AggregateSpec, ...]:
        return self._aggregates

    @property
    def schema(self) -> Schema:
        return self._schema

    def create_operator(self) -> Aggregate:
        return Aggregate(self._child.create_operator(), self._resolved, self._schema)


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
