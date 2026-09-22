"""Focused Phase 11 global-aggregation coverage."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog
from strata_engine.execution import Aggregate, Operator, OperatorClosedError
from strata_engine.execution.aggregate import ResolvedAggregate
from strata_engine.planning import AggregatePlan, AggregateSpec, Planner, QueryRequest
from strata_engine.schema import Column, DataType, DuplicateColumnError, Schema, Tuple, TypeMismatchError
from strata_engine.sql import AggregateList, Binder, Lexer, Parser, SQLBindingError, SQLParseError


class ListOperator(Operator):
    """Small execution test child that supplies schema-bound rows."""

    def __init__(self, schema: Schema, rows: list[tuple[object, ...]]) -> None:
        self._schema = schema
        self._rows = rows
        self._open = False
        self._position = 0

    @property
    def schema(self) -> Schema:
        return self._schema

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True
        self._position = 0

    def next(self):
        if not self._open:
            raise OperatorClosedError("closed")
        if self._position == len(self._rows):
            return None
        row = Tuple(self._rows[self._position], self._schema)
        self._position += 1
        return row

    def close(self) -> None:
        self._open = False


def test_aggregate_execution_null_empty_multiple_and_lifecycle() -> None:
    schema = Schema([Column("age", DataType.INTEGER, nullable=True)])
    output = Schema([
        Column("count_star", DataType.BIGINT),
        Column("count_age", DataType.BIGINT),
        Column("sum_age", DataType.BIGINT, nullable=True),
        Column("avg_age", DataType.FLOAT, nullable=True),
        Column("min_age", DataType.INTEGER, nullable=True),
        Column("max_age", DataType.INTEGER, nullable=True),
    ])
    specs = [
        ResolvedAggregate("COUNT", None, None),
        ResolvedAggregate("COUNT", 0, DataType.INTEGER),
        ResolvedAggregate("SUM", 0, DataType.INTEGER),
        ResolvedAggregate("AVG", 0, DataType.INTEGER),
        ResolvedAggregate("MIN", 0, DataType.INTEGER),
        ResolvedAggregate("MAX", 0, DataType.INTEGER),
    ]
    aggregate = Aggregate(ListOperator(schema, [(2,), (None,), (6,)]), specs, output)
    with pytest.raises(OperatorClosedError):
        aggregate.next()
    aggregate.open()
    assert aggregate.next().values == (3, 2, 8, 4.0, 2, 6)
    assert aggregate.next() is None
    assert aggregate.next() is None
    aggregate.close()
    aggregate.close()
    aggregate.open()
    assert aggregate.next().values == (3, 2, 8, 4.0, 2, 6)


def test_aggregate_empty_and_type_rules() -> None:
    schema = Schema([Column("name", DataType.VARCHAR, nullable=True, max_length=10)])
    output = Schema([Column("count_star", DataType.BIGINT), Column("min_name", DataType.VARCHAR, True, 10)])
    aggregate = Aggregate(
        ListOperator(schema, []),
        [ResolvedAggregate("COUNT", None, None), ResolvedAggregate("MIN", 0, DataType.VARCHAR)],
        output,
    )
    aggregate.open()
    assert aggregate.next().values == (0, None)


@pytest.mark.parametrize(
    ("input_type", "values", "operation", "expected", "output_type", "max_length"),
    [
        (DataType.BIGINT, [(4,), (2,)], "SUM", 6, DataType.BIGINT, None),
        (DataType.FLOAT, [(1.5,), (2.5,)], "SUM", 4.0, DataType.FLOAT, None),
        (DataType.BIGINT, [(4,), (2,)], "AVG", 3.0, DataType.FLOAT, None),
        (DataType.FLOAT, [(1.5,), (2.5,)], "AVG", 2.0, DataType.FLOAT, None),
        (DataType.BOOLEAN, [(True,), (False,)], "MIN", False, DataType.BOOLEAN, None),
        (DataType.BOOLEAN, [(True,), (False,)], "MAX", True, DataType.BOOLEAN, None),
        (DataType.VARCHAR, [("z",), ("a",)], "MIN", "a", DataType.VARCHAR, 8),
        (DataType.VARCHAR, [("z",), ("a",)], "MAX", "z", DataType.VARCHAR, 8),
    ],
)
def test_aggregate_supported_type_results(
    input_type, values, operation, expected, output_type, max_length
) -> None:
    schema = Schema([Column("value", input_type, nullable=True, max_length=max_length)])
    output = Schema([Column("result", output_type, nullable=True, max_length=max_length)])
    aggregate = Aggregate(
        ListOperator(schema, values),
        [ResolvedAggregate(operation, 0, input_type)],
        output,
    )
    aggregate.open()
    assert aggregate.next().values == (expected,)


def test_aggregate_plan_schema_validation_naming_and_duplicates(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "database")
    try:
        long_name = "a" * 64
        table = catalog.create_table(
            "metrics",
            Schema([Column("age", DataType.INTEGER, nullable=True), Column(long_name, DataType.VARCHAR, True, 4)]),
        )
        plan = AggregatePlan(
            Planner().plan(QueryRequest(table)),
            [AggregateSpec("sum", "AGE"), AggregateSpec("min", long_name)],
        )
        assert plan.schema.column_names == ("sum_age", "min_" + "a" * 60)
        assert plan.schema[0].data_type == DataType.BIGINT
        assert plan.schema[0].nullable is True
        assert plan.schema[1].max_length == 4
        with pytest.raises(DuplicateColumnError):
            AggregatePlan(Planner().plan(QueryRequest(table)), [AggregateSpec("MAX", "age"), AggregateSpec("max", "AGE")])
        with pytest.raises(TypeMismatchError):
            AggregatePlan(Planner().plan(QueryRequest(table)), [AggregateSpec("SUM", long_name)])
    finally:
        catalog.close()


def test_sql_aggregate_path_and_restrictions(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "database")
    try:
        table = catalog.create_table("users", Schema([Column("age", DataType.INTEGER, nullable=True)]))
        table.insert([1])
        table.insert([None])
        statement = Parser(Lexer("SELECT count(*), AVG(age), MAX(age) FROM users LIMIT 1").tokenize()).parse()
        assert isinstance(statement.projection, AggregateList)
        request = Binder(catalog).bind(statement)
        assert tuple(spec.operation for spec in request.aggregates) == ("COUNT", "AVG", "MAX")
        operator = Planner().plan(request).create_operator()
        with operator:
            assert [row.values for row in operator] == [(2, 1.0, 1)]
        with pytest.raises(SQLParseError):
            Parser(Lexer("SELECT age, COUNT(*) FROM users").tokenize()).parse()
        with pytest.raises(SQLParseError):
            Parser(Lexer("SELECT SUM(*) FROM users").tokenize()).parse()
        with pytest.raises(SQLBindingError):
            Binder(catalog).bind(Parser(Lexer("SELECT COUNT(*) FROM users ORDER BY age").tokenize()).parse())
    finally:
        catalog.close()
