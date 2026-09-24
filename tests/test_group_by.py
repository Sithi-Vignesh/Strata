"""Focused Phase 13 GROUP BY and grouped-aggregation coverage."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog
from strata_engine.execution import Aggregate, Operator, OperatorClosedError
from strata_engine.execution.aggregate import ResolvedAggregate, ResolvedAggregateOutput
from strata_engine.planning import (
    AggregateOutputSpec,
    AggregatePlan,
    AggregateSpec,
    Planner,
    TableScanPlan,
)
from strata_engine.schema import (
    Column,
    ColumnNotFoundError,
    DataType,
    DuplicateColumnError,
    Schema,
    Tuple,
)
from strata_engine.sql import (
    Binder,
    GroupedAggregateList,
    Lexer,
    Parser,
    SQLBindingError,
    SQLParseError,
    TokenType,
)


class Rows(Operator):
    """Controllable schema-bound source for aggregate execution tests."""

    def __init__(
        self,
        schema: Schema,
        rows: tuple[tuple[object, ...], ...] = (),
        fail_open: Exception | None = None,
        fail_next: Exception | None = None,
    ) -> None:
        self._schema = schema
        self._rows = rows
        self._fail_open = fail_open
        self._fail_next = fail_next
        self._open = False
        self._position = 0
        self.closes = 0

    @property
    def schema(self) -> Schema:
        return self._schema

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if self._fail_open is not None:
            raise self._fail_open
        self._open = True
        self._position = 0

    def next(self) -> Tuple | None:
        if not self._open:
            raise OperatorClosedError("closed")
        if self._fail_next is not None:
            raise self._fail_next
        if self._position == len(self._rows):
            return None
        row = Tuple(self._rows[self._position], self._schema)
        self._position += 1
        return row

    def close(self) -> None:
        self.closes += 1
        self._open = False


def _execute(catalog: Catalog, sql: str) -> tuple[tuple[str, ...], list[tuple[object, ...]]]:
    request = Binder(catalog).bind(Parser(Lexer(sql).tokenize()).parse())
    operator = Planner().plan(request).create_operator()
    with operator:
        return operator.schema.column_names, [row.values for row in operator]


def _count_layout(group_count: int = 1) -> tuple[ResolvedAggregateOutput, ...]:
    groups = tuple(ResolvedAggregateOutput("GROUP", index) for index in range(group_count))
    return groups + (ResolvedAggregateOutput("AGGREGATE", 0),)


@pytest.fixture
def catalog(tmp_path: Path):
    instance = Catalog(tmp_path / "database")
    employees = instance.create_table(
        "employees",
        Schema([
            Column("department", DataType.VARCHAR, nullable=True, max_length=12),
            Column("name", DataType.VARCHAR, max_length=12),
            Column("salary", DataType.INTEGER, nullable=True),
            Column("active", DataType.BOOLEAN),
        ]),
    )
    users = instance.create_table("users", Schema([Column("id", DataType.INTEGER)]))
    orders = instance.create_table("orders", Schema([Column("user_id", DataType.INTEGER)]))
    for row in (
        ("Sales", "Ada", 4, True),
        ("Sales", "Bea", None, True),
        ("Engineering", "Cal", 8, True),
        ("Support", "Dia", 2, True),
        ("Ignored", "Eli", 9, False),
    ):
        employees.insert(row)
    users.insert([1])
    orders.insert([1])
    yield instance
    instance.close()


def test_grouped_aggregate_functions_and_all_null_inputs() -> None:
    source = Schema([Column("department", DataType.VARCHAR, nullable=True, max_length=12), Column("value", DataType.INTEGER, nullable=True)])
    output = Schema([source["department"], Column("count_star", DataType.BIGINT), Column("count_value", DataType.BIGINT), Column("sum_value", DataType.BIGINT, nullable=True), Column("avg_value", DataType.FLOAT, nullable=True), Column("min_value", DataType.INTEGER, nullable=True), Column("max_value", DataType.INTEGER, nullable=True)])
    aggregates = (ResolvedAggregate("COUNT", None, None), ResolvedAggregate("COUNT", 1, DataType.INTEGER), ResolvedAggregate("SUM", 1, DataType.INTEGER), ResolvedAggregate("AVG", 1, DataType.INTEGER), ResolvedAggregate("MIN", 1, DataType.INTEGER), ResolvedAggregate("MAX", 1, DataType.INTEGER))
    layout = (ResolvedAggregateOutput("GROUP", 0),) + tuple(ResolvedAggregateOutput("AGGREGATE", index) for index in range(len(aggregates)))
    aggregate = Aggregate(Rows(source, (("Sales", 1), ("Sales", None), ("Sales", 3), ("Empty", None), ("Empty", None))), aggregates, output, (0,), layout)
    with aggregate:
        assert [row.values for row in aggregate] == [("Sales", 3, 2, 4, 2.0, 1, 3), ("Empty", 2, 0, None, None, None, None)]


def test_grouped_composite_null_keys_and_interleaved_layout() -> None:
    source = Schema([Column("department", DataType.VARCHAR, nullable=True, max_length=10), Column("site", DataType.VARCHAR, nullable=True, max_length=10), Column("salary", DataType.INTEGER, nullable=True)])
    output = Schema([Column("count_star", DataType.BIGINT), source["department"], Column("avg_salary", DataType.FLOAT, nullable=True), source["site"]])
    aggregate = Aggregate(Rows(source, ((None, "NY", 2), (None, "NY", None), (None, "LA", 6))), (ResolvedAggregate("COUNT", None, None), ResolvedAggregate("AVG", 2, DataType.INTEGER)), output, (0, 1), (ResolvedAggregateOutput("AGGREGATE", 0), ResolvedAggregateOutput("GROUP", 0), ResolvedAggregateOutput("AGGREGATE", 1), ResolvedAggregateOutput("GROUP", 1)))
    with aggregate:
        assert [row.values for row in aggregate] == [(2, None, 2.0, "NY"), (1, None, 6.0, "LA")]


@pytest.mark.parametrize(("data_type", "values", "max_length"), [
    (DataType.INTEGER, ((1,), (1,), (2,)), None),
    (DataType.BIGINT, ((2**40,), (2**40,), (2**41,)), None),
    (DataType.FLOAT, ((1.5,), (1.5,), (2.5,)), None),
    (DataType.BOOLEAN, ((True,), (True,), (False,)), None),
    (DataType.VARCHAR, (("a",), ("a",), ("b",)), 8),
])
def test_grouping_key_data_types(data_type, values, max_length) -> None:
    source = Schema([Column("key", data_type, max_length=max_length)])
    aggregate = Aggregate(Rows(source, values), (ResolvedAggregate("COUNT", None, None),), Schema([source["key"], Column("count_star", DataType.BIGINT)]), (0,), _count_layout())
    with aggregate:
        assert [row.values for row in aggregate] == [(values[0][0], 2), (values[2][0], 1)]


def test_grouped_empty_input_is_distinct_from_global_empty_input() -> None:
    source = Schema([Column("department", DataType.VARCHAR, nullable=True, max_length=10)])
    grouped = Aggregate(Rows(source), (ResolvedAggregate("COUNT", None, None),), Schema([source["department"], Column("count_star", DataType.BIGINT)]), (0,), _count_layout())
    global_aggregate = Aggregate(Rows(source), (ResolvedAggregate("COUNT", None, None),), Schema([Column("count_star", DataType.BIGINT)]))
    with grouped:
        assert list(grouped) == []
    with global_aggregate:
        assert [row.values for row in global_aggregate] == [(0,)]


def test_grouped_lifecycle_reopen_and_failure_cleanup() -> None:
    source = Schema([Column("department", DataType.VARCHAR, max_length=10)])
    output = Schema([source["department"], Column("count_star", DataType.BIGINT)])
    child = Rows(source, (("Sales",), ("Sales",), ("Support",)))
    aggregate = Aggregate(child, (ResolvedAggregate("COUNT", None, None),), output, (0,), _count_layout())
    with pytest.raises(OperatorClosedError):
        aggregate.next()
    aggregate.open()
    assert [row.values for row in aggregate] == [("Sales", 2), ("Support", 1)]
    assert aggregate.next() is None
    assert aggregate.next() is None
    aggregate.close()
    aggregate.close()
    aggregate.open()
    assert aggregate.next().values == ("Sales", 2)
    aggregate.close()
    aggregate.open()
    assert aggregate.next().values == ("Sales", 2)
    for failure, field in ((RuntimeError("open failure"), "open"), (RuntimeError("scan failure"), "next")):
        failing_child = Rows(source, (("Sales",),), fail_open=failure if field == "open" else None, fail_next=failure if field == "next" else None)
        failing = Aggregate(failing_child, (ResolvedAggregate("COUNT", None, None),), output, (0,), _count_layout())
        with pytest.raises(RuntimeError) as raised:
            failing.open()
        assert raised.value is failure
        assert failing_child.closes >= 1
        assert not failing.is_open


def test_grouped_sql_order_limit_offset_and_generated_aggregate_name(catalog: Catalog) -> None:
    names, rows = _execute(catalog, "SELECT department, COUNT(*) FROM employees WHERE active = TRUE GROUP BY department ORDER BY department LIMIT 2 OFFSET 1")
    assert names == ("department", "count_star")
    assert rows == [("Sales", 2), ("Support", 1)]
    assert _execute(catalog, "SELECT department, COUNT(*) FROM employees WHERE active = TRUE GROUP BY department ORDER BY count_star DESC")[1] == [("Sales", 2), ("Engineering", 1), ("Support", 1)]


def test_group_by_parser_forms_and_clause_rejections(catalog: Catalog) -> None:
    tokens = Lexer("SELECT department, COUNT(*) FROM employees GROUP BY department").tokenize()
    assert TokenType.GROUP in tuple(token.type for token in tokens)
    one = Parser(tokens).parse()
    assert one.group_by is not None
    assert tuple(ref.column_name for ref in one.group_by) == ("department",)
    multi = Parser(Lexer("SELECT COUNT(*), department, salary FROM employees GROUP BY department, salary").tokenize()).parse()
    assert isinstance(multi.projection, GroupedAggregateList)
    assert tuple(ref.column_name for ref in multi.group_by or ()) == ("department", "salary")
    for sql in ("SELECT department, COUNT(*) FROM employees GROUP", "SELECT department, COUNT(*) FROM employees GROUP BY", "SELECT department FROM employees GROUP BY department ORDER BY department WHERE active = TRUE", "SELECT department, COUNT(*) FROM employees GROUP BY department HAVING COUNT(*) > 1", "SELECT department, COUNT(*) FROM employees GROUP BY department ORDER BY COUNT(*)"):
        with pytest.raises(SQLParseError):
            Parser(Lexer(sql).tokenize()).parse()
    with pytest.raises(SQLBindingError):
        Binder(catalog).bind(Parser(Lexer("SELECT department FROM employees GROUP BY department").tokenize()).parse())


def test_grouped_binder_and_planning_rejections(catalog: Catalog) -> None:
    binder = Binder(catalog)
    for sql in ("SELECT department, name, COUNT(*) FROM employees GROUP BY department", "SELECT department, COUNT(*) FROM employees GROUP BY department, Department", "SELECT department, COUNT(*) FROM employees GROUP BY employees.department"):
        with pytest.raises(SQLBindingError):
            binder.bind(Parser(Lexer(sql).tokenize()).parse())
    request = binder.bind(Parser(Lexer("SELECT department, COUNT(*) FROM employees GROUP BY department ORDER BY salary").tokenize()).parse())
    with pytest.raises(ColumnNotFoundError):
        Planner().plan(request)


def test_grouped_plan_metadata_duplicate_names_and_fresh_operator_trees(catalog: Catalog) -> None:
    employees = catalog.get_table("employees")
    plan = AggregatePlan(TableScanPlan(employees), (AggregateSpec("COUNT"),), ("DEPARTMENT",), (AggregateOutputSpec("GROUP", 0), AggregateOutputSpec("AGGREGATE", 0)))
    assert plan.schema[0].data_type == DataType.VARCHAR
    assert plan.schema[0].nullable is True
    assert plan.schema[0].max_length == 12
    first = plan.create_operator()
    second = plan.create_operator()
    assert first is not second
    assert first.child is not second.child
    with pytest.raises(DuplicateColumnError):
        AggregatePlan(TableScanPlan(employees), (AggregateSpec("COUNT"),), ("department", "DEPARTMENT"), (AggregateOutputSpec("AGGREGATE", 0),))
