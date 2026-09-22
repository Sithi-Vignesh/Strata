"""Tests for Phase 7's immutable query-planning layer."""

from pathlib import Path

import pytest

from strata_engine.catalog import Table
from strata_engine.execution import ComparisonPredicate, Filter, Limit, Projection, Sort, TableScan
from strata_engine.planning import (
    FilterPlan,
    LimitPlan,
    OrderBy,
    Plan,
    Planner,
    PlanningError,
    ProjectionPlan,
    QueryRequest,
    TableScanPlan,
    SortPlan,
)
from strata_engine.exceptions import StrataError
from strata_engine.schema import (
    Column,
    ColumnNotFoundError,
    DataType,
    DuplicateColumnError,
    Schema,
    TypeMismatchError,
)
from strata_engine.storage import BufferPoolManager, HeapFile, PageFile


@pytest.fixture
def populated_table(tmp_path: Path):
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR, max_length=50),
        Column("score", DataType.FLOAT, nullable=True),
    ])
    page_file = PageFile(tmp_path / "planning.db")
    table = Table(1, "users", schema, HeapFile(BufferPoolManager(page_file, pool_size=3)))
    for row in ((1, "Alice", 95.5), (2, "Bob", 80.0), (3, "Cara", 70.0)):
        table.insert(row)
    yield table
    table.close()


@pytest.fixture
def wide_table(tmp_path: Path):
    schema = Schema([Column(f"c{i}", DataType.INTEGER) for i in range(256)])
    page_file = PageFile(tmp_path / "wide.db")
    table = Table(2, "wide", schema, HeapFile(BufferPoolManager(page_file, pool_size=1)))
    yield table
    table.close()


def test_table_scan_plan_schema_and_fresh_operators(populated_table: Table) -> None:
    plan = TableScanPlan(populated_table)

    assert plan.schema is populated_table.schema
    first = plan.create_operator()
    second = plan.create_operator()
    assert isinstance(first, TableScan)
    assert first is not second
    assert first.table is second.table is populated_table


def test_table_scan_plan_construction_does_not_scan(populated_table: Table, monkeypatch) -> None:
    def fail_scan(self):
        raise AssertionError("planning must not scan rows")

    monkeypatch.setattr(Table, "scan", fail_scan)
    plan = TableScanPlan(populated_table)
    assert plan.schema is populated_table.schema
    assert isinstance(plan.create_operator(), TableScan)


def test_concrete_plans_reject_attribute_reassignment(populated_table: Table) -> None:
    scan = TableScanPlan(populated_table)
    filtered = FilterPlan(scan, ComparisonPredicate("id", ">", 1))
    projected = ProjectionPlan(scan, ("id",))

    with pytest.raises(AttributeError):
        scan._table = None  # type: ignore[misc, assignment]
    with pytest.raises(AttributeError):
        filtered._predicate = None  # type: ignore[misc, assignment]
    with pytest.raises(AttributeError):
        projected._columns = ()  # type: ignore[misc, assignment]


def test_filter_plan_validates_during_construction(populated_table: Table) -> None:
    child = TableScanPlan(populated_table)
    predicate = ComparisonPredicate("id", ">", 1)
    plan = FilterPlan(child, predicate)

    assert plan.schema is child.schema
    assert plan.predicate is predicate
    operator = plan.create_operator()
    assert isinstance(operator, Filter)
    assert isinstance(operator.child, TableScan)

    with pytest.raises(ColumnNotFoundError):
        FilterPlan(child, ComparisonPredicate("missing", "=", 1))
    with pytest.raises(TypeMismatchError):
        FilterPlan(child, ComparisonPredicate("id", "=", "one"))


def test_projection_plan_derives_schema_and_preserves_order(populated_table: Table) -> None:
    child = TableScanPlan(populated_table)
    plan = ProjectionPlan(child, ["NAME", "id"])

    assert plan.columns == ("NAME", "id")
    assert plan.schema is not child.schema
    assert plan.schema.column_names == ("name", "id")
    assert plan.schema.columns[0] is populated_table.schema["name"]
    assert plan.schema.columns[1] is populated_table.schema["id"]
    operator = plan.create_operator()
    assert isinstance(operator, Projection)
    assert isinstance(operator.child, TableScan)


@pytest.mark.parametrize(
    ("columns", "exception"),
    [
        ([], ValueError),
        (["id", "ID"], DuplicateColumnError),
        (["missing"], ColumnNotFoundError),
        (["id", 1], TypeError),
    ],
)
def test_projection_plan_validation(populated_table: Table, columns, exception) -> None:
    with pytest.raises(exception):
        ProjectionPlan(TableScanPlan(populated_table), columns)


def test_projection_plan_accepts_256_columns(wide_table: Table) -> None:
    plan = ProjectionPlan(TableScanPlan(wide_table), [f"c{i}" for i in range(256)])

    assert len(plan.columns) == len(plan.schema.columns) == 256


def test_projection_plan_rejects_more_than_256_columns(wide_table: Table) -> None:
    with pytest.raises(ValueError):
        ProjectionPlan(TableScanPlan(wide_table), [f"c{i}" for i in range(256)] + ["c0"])


def test_projection_plan_does_not_retain_mutable_input(populated_table: Table) -> None:
    requested = ["name", "id"]
    plan = ProjectionPlan(TableScanPlan(populated_table), requested)
    requested[:] = ["score"]

    assert plan.columns == ("name", "id")
    assert plan.schema.column_names == ("name", "id")


def test_query_request_is_frozen_and_normalizes_projection(populated_table: Table) -> None:
    requested = ["name", "id"]
    predicate = ComparisonPredicate("id", ">", 1)
    request = QueryRequest(populated_table, predicate, requested)  # type: ignore[arg-type]
    requested[:] = ["score"]

    assert request.projection == ("name", "id")
    with pytest.raises(AttributeError):
        request.table = populated_table  # type: ignore[misc]
    with pytest.raises(AttributeError):
        request.predicate = None  # type: ignore[misc]
    with pytest.raises(AttributeError):
        request.projection = ("score",)  # type: ignore[misc]


def test_planning_public_api_exports_approved_names() -> None:
    from strata_engine import (
        FilterPlan as PublicFilterPlan,
        Plan as PublicPlan,
        Planner as PublicPlanner,
        PlanningError as PublicPlanningError,
        ProjectionPlan as PublicProjectionPlan,
        QueryRequest as PublicQueryRequest,
        TableScanPlan as PublicTableScanPlan,
    )

    assert (
        PublicPlan,
        PublicTableScanPlan,
        PublicFilterPlan,
        PublicProjectionPlan,
        PublicQueryRequest,
        PublicPlanner,
        PublicPlanningError,
    ) == (Plan, TableScanPlan, FilterPlan, ProjectionPlan, QueryRequest, Planner, PlanningError)


def test_planning_error_is_a_strata_error() -> None:
    assert issubclass(PlanningError, StrataError)


def test_query_request_distinguishes_empty_projection(populated_table: Table) -> None:
    no_projection = QueryRequest(populated_table)
    empty_projection = QueryRequest(populated_table, projection=())

    assert no_projection.projection is None
    assert empty_projection.projection == ()
    with pytest.raises(ValueError):
        Planner().plan(empty_projection)


@pytest.mark.parametrize(
    ("request_factory", "expected_types"),
    [
        (lambda table: QueryRequest(table), (TableScanPlan,)),
        (
            lambda table: QueryRequest(table, ComparisonPredicate("id", ">", 1)),
            (FilterPlan, TableScanPlan),
        ),
        (lambda table: QueryRequest(table, projection=("name",)), (ProjectionPlan, TableScanPlan)),
        (
            lambda table: QueryRequest(
                table, ComparisonPredicate("id", ">", 1), projection=("name",)
            ),
            (ProjectionPlan, FilterPlan, TableScanPlan),
        ),
    ],
)
def test_planner_creates_exact_supported_shapes(populated_table: Table, request_factory, expected_types) -> None:
    plan = Planner().plan(request_factory(populated_table))
    found_types = []
    current = plan
    while True:
        found_types.append(type(current))
        if isinstance(current, TableScanPlan):
            break
        current = current.child
    assert tuple(found_types) == expected_types


def test_planner_is_deterministic_and_does_not_scan(populated_table: Table, monkeypatch) -> None:
    def fail_scan(self):
        raise AssertionError("planning must not scan rows")

    monkeypatch.setattr(Table, "scan", fail_scan)
    request = QueryRequest(populated_table, ComparisonPredicate("id", ">", 1), ("name",))
    first = Planner().plan(request)
    second = Planner().plan(request)
    assert type(first) is type(second) is ProjectionPlan
    assert first.schema == second.schema


def test_planned_query_executes_with_independent_operator_trees(populated_table: Table) -> None:
    request = QueryRequest(
        populated_table,
        ComparisonPredicate("score", ">=", 80.0),
        ("name", "score"),
    )
    plan = Planner().plan(request)
    first = plan.create_operator()
    second = plan.create_operator()

    assert first is not second
    assert first.child is not second.child
    assert first.child.child is not second.child.child

    with first:
        first_rows = [row.values for row in first]
    with second:
        second_rows = [row.values for row in second]

    assert first_rows == second_rows == [("Alice", 95.5), ("Bob", 80.0)]
    assert populated_table.is_closed is False


def test_order_by_sort_plan_and_limit_plan_contracts(populated_table: Table) -> None:
    scan = TableScanPlan(populated_table)
    order_by = [OrderBy("SCORE", descending=True), OrderBy("id")]
    sort_plan = SortPlan(scan, order_by)
    assert sort_plan.schema is scan.schema
    assert sort_plan.order_by == tuple(order_by)
    sort = sort_plan.create_operator()
    assert isinstance(sort, Sort)
    assert sort.sort_keys[0].column_index == 2
    assert sort.child is not sort_plan.create_operator().child

    limit_plan = LimitPlan(sort_plan, 0, 2)
    assert limit_plan.schema is scan.schema
    assert isinstance(limit_plan.create_operator(), Limit)
    with pytest.raises(DuplicateColumnError):
        SortPlan(scan, [OrderBy("id"), OrderBy("ID", True)])
    with pytest.raises(ColumnNotFoundError):
        SortPlan(scan, [OrderBy("missing")])
    with pytest.raises(ValueError):
        SortPlan(scan, [])
    with pytest.raises(TypeError):
        OrderBy("id", 1)  # type: ignore[arg-type]


def test_query_request_ordering_limit_and_planner_shape(populated_table: Table) -> None:
    request = QueryRequest(
        populated_table,
        projection=("name",),
        order_by=[OrderBy("score", True)],  # type: ignore[arg-type]
        limit=2,
        offset=1,
    )
    assert request.order_by == (OrderBy("score", True),)
    plan = Planner().plan(request)
    assert isinstance(plan, LimitPlan)
    assert isinstance(plan.child, ProjectionPlan)
    assert isinstance(plan.child.child, SortPlan)
    assert isinstance(plan.child.child.child, TableScanPlan)
    assert QueryRequest(populated_table, order_by=()).order_by == ()
    with pytest.raises(ValueError):
        Planner().plan(QueryRequest(populated_table, order_by=()))
    with pytest.raises(ValueError):
        QueryRequest(populated_table, offset=1)
    with pytest.raises(TypeError):
        QueryRequest(populated_table, limit=True)  # type: ignore[arg-type]
