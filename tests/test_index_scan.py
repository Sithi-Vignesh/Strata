"""Focused Phase 21A coverage for deterministic index-backed table access."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog
from strata_engine.execution import (
    AndPredicate,
    ComparisonPredicate,
    IndexScan,
    IsNullPredicate,
    NotPredicate,
    OperatorClosedError,
    OrPredicate,
)
from strata_engine.planning import FilterPlan, IndexScanPlan, JoinPlan, Planner, QueryRequest, TableScanPlan
from strata_engine.schema import Column, DataType, Schema
from strata_engine.storage import RecordNotFoundError, StorageClosedError
from strata_engine.sql import Binder, Lexer, Parser


def _schema() -> Schema:
    return Schema([
        Column("id", DataType.INTEGER, nullable=False),
        Column("score", DataType.INTEGER, nullable=False),
        Column("kind", DataType.VARCHAR, nullable=True, max_length=32),
    ])


@pytest.fixture
def indexed_table(tmp_path: Path):
    catalog = Catalog(tmp_path / "database", default_pool_size=2)
    table = catalog.create_table("events", _schema())
    rids = [
        table.insert([4, 20, "same"]),
        table.insert([1, 10, "same"]),
        table.insert([3, 30, "other"]),
        table.insert([2, 20, None]),
    ]
    catalog.create_index("events_score", "events", "score")
    catalog.create_index("events_kind", "events", "kind")
    yield catalog, table, rids
    catalog.close()


@pytest.mark.parametrize(
    ("op", "literal", "expected"),
    [
        ("=", 20, [4, 2]),
        ("<", 20, [1]),
        ("<=", 20, [4, 1, 2]),
        (">", 20, [3]),
        (">=", 20, [4, 3, 2]),
    ],
)
def test_index_scan_conditions_preserve_rid_order(indexed_table, op, literal, expected) -> None:
    _catalog, table, _rids = indexed_table
    scan = IndexScan(table, table.index_for_column("score"), op, literal)

    assert scan.schema is table.schema
    with scan:
        assert [row["id"] for row in scan] == expected
    assert scan.rids_selected == len(expected)
    assert scan.rows_fetched == len(expected)
    assert scan.tree_pages_visited >= 1
    assert scan.leaf_entries_examined >= len(expected)


def test_index_scan_lifecycle_metrics_and_borrowed_ownership(indexed_table) -> None:
    _catalog, table, _rids = indexed_table
    index = table.index_for_column("score")
    assert index is not None
    scan = IndexScan(table, index, "=", 20)

    with pytest.raises(OperatorClosedError):
        scan.next()
    scan.open()
    pages, entries = scan.tree_pages_visited, scan.leaf_entries_examined
    assert scan.next()["id"] == 4
    assert scan.rows_fetched == 1
    while scan.next() is not None:
        pass
    assert scan.next() is None
    assert scan.rows_fetched == 2
    index.tree.search(30)
    assert (scan.tree_pages_visited, scan.leaf_entries_examined) == (pages, entries)
    scan.close()
    assert not table.is_closed
    assert not index.tree.is_closed
    scan.open()
    assert scan.rows_fetched == 0
    assert scan.rids_selected == 2
    scan.close()


def test_index_scan_zero_matches_closed_table_and_stale_rid(indexed_table) -> None:
    _catalog, table, rids = indexed_table
    index = table.index_for_column("score")
    assert index is not None
    zero = IndexScan(table, index, "=", 999)
    with zero:
        assert zero.next() is None
    assert zero.rids_selected == zero.rows_fetched == 0

    stale = IndexScan(table, index, "=", 10)
    table.heap_file.delete_record(rids[1])
    stale.open()
    with pytest.raises(RecordNotFoundError):
        stale.next()

    table.close()
    with pytest.raises(StorageClosedError):
        zero.open()


def test_table_index_lookup_resolves_case_and_lowest_index_id(indexed_table) -> None:
    catalog, table, _rids = indexed_table
    first = table.index_for_column("SCORE")
    assert first is not None
    catalog.create_index("events_score_second", "events", "score")
    assert table.index_for_column("score") is first
    assert table.index_for_column("kind") is not None
    assert table.index_for_column("id") is None


def test_index_scan_plan_is_immutable_and_creates_index_scan(indexed_table) -> None:
    _catalog, table, _rids = indexed_table
    index = table.index_for_column("score")
    assert index is not None
    plan = IndexScanPlan(table, index, ">=", 20)
    assert plan.schema is table.schema
    assert (plan.table, plan.index, plan.op, plan.literal) == (table, index, ">=", 20)
    with pytest.raises(AttributeError):
        plan._op = "="  # type: ignore[misc]
    operator = plan.create_operator()
    assert isinstance(operator, IndexScan)
    assert (operator.index, operator.op, operator.literal) == (index, ">=", 20)


@pytest.mark.parametrize("op", ["=", "<", "<=", ">", ">="])
def test_planner_selects_index_scan_for_eligible_comparisons(indexed_table, op) -> None:
    _catalog, table, _rids = indexed_table
    plan = Planner().plan(QueryRequest(table, ComparisonPredicate("score", op, 20)))
    assert isinstance(plan, FilterPlan)
    assert isinstance(plan.child, IndexScanPlan)
    assert plan.child.index.name == "events_score"


@pytest.mark.parametrize(
    "predicate",
    [
        ComparisonPredicate("id", "=", 1),
        ComparisonPredicate("score", "!=", 1),
        IsNullPredicate("kind"),
        OrPredicate(ComparisonPredicate("score", "=", 1), ComparisonPredicate("score", "=", 2)),
        NotPredicate(ComparisonPredicate("score", "=", 1)),
    ],
)
def test_planner_falls_back_for_ineligible_predicates(indexed_table, predicate) -> None:
    _catalog, table, _rids = indexed_table
    plan = Planner().plan(QueryRequest(table, predicate))
    assert isinstance(plan, FilterPlan)
    assert isinstance(plan.child, TableScanPlan)


def test_planner_uses_first_eligible_and_comparison_and_full_filter(indexed_table) -> None:
    _catalog, table, _rids = indexed_table
    predicate = AndPredicate(
        ComparisonPredicate("id", "=", 4),
        AndPredicate(ComparisonPredicate("kind", "=", "same"), ComparisonPredicate("score", "=", 20)),
    )
    plan = Planner().plan(QueryRequest(table, predicate))
    assert isinstance(plan, FilterPlan)
    assert plan.predicate is predicate
    assert isinstance(plan.child, IndexScanPlan)
    assert plan.child.index.name == "events_kind"


def test_sql_index_scan_integration_keeps_wrappers_and_results(indexed_table) -> None:
    catalog, table, _rids = indexed_table
    request = Binder(catalog).bind(
        Parser(Lexer("SELECT id FROM events WHERE score >= 20 AND kind = 'same' ORDER BY id LIMIT 2").tokenize()).parse()
    )
    plan = Planner().plan(request)
    assert plan.child.child.child.child.__class__ is IndexScanPlan
    operator = plan.create_operator()
    with operator:
        assert [row.values for row in operator] == [(4,)]
    fallback = Planner().plan(QueryRequest(table))
    assert isinstance(fallback, TableScanPlan)


def test_joins_keep_existing_table_scan_inputs(indexed_table) -> None:
    catalog, _table, _rids = indexed_table
    other = catalog.create_table("other_events", _schema())
    other.insert([4, 40, "join"])
    request = Binder(catalog).bind(
        Parser(
            Lexer(
                "SELECT events.id FROM events JOIN other_events "
                "ON events.id = other_events.id"
            ).tokenize()
        ).parse()
    )
    plan = Planner().plan(request)
    join = plan.child
    assert isinstance(join, JoinPlan)
    assert isinstance(join.left, TableScanPlan)
    assert isinstance(join.right, TableScanPlan)
