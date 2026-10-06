"""Focused coverage for RID-aware mutation target selection."""

from pathlib import Path

import pytest

from strata_engine.catalog.table import Table
from strata_engine.execution import (
    AndPredicate,
    ComparisonPredicate,
    IsNullPredicate,
    MutationTargetScan,
    NotPredicate,
)
from strata_engine.schema import Column, ColumnNotFoundError, DataType, Schema
from strata_engine.storage import BufferPoolManager, HeapFile, PageFile


@pytest.fixture
def mutation_table(tmp_path: Path):
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR, max_length=32),
        Column("score", DataType.INTEGER, nullable=True),
        Column("active", DataType.BOOLEAN),
    ])
    page_file = PageFile(tmp_path / "mutation_scan.db")
    buffer_pool = BufferPoolManager(page_file, pool_size=3)
    table = Table(1, "items", schema, HeapFile(buffer_pool))
    try:
        yield table
    finally:
        table.close()


def _insert_rows(table: Table):
    return (
        table.insert([1, "alpha", None, True]),
        table.insert([2, "beta", 10, False]),
        table.insert([3, "gamma", 20, True]),
        table.insert([4, "delta", None, False]),
    )


def test_collects_all_rows_in_table_scan_order_and_preserves_rids(mutation_table: Table) -> None:
    _insert_rows(mutation_table)

    expected = tuple(mutation_table.scan())
    targets = MutationTargetScan(mutation_table).collect()

    assert targets == expected
    assert tuple(record_id for record_id, _row in targets) == tuple(
        record_id for record_id, _row in expected
    )


def test_collects_matching_rows_with_exact_table_rids(mutation_table: Table) -> None:
    _insert_rows(mutation_table)

    targets = MutationTargetScan(
        mutation_table, ComparisonPredicate("score", ">=", 10)
    ).collect()
    expected = tuple(
        (record_id, row)
        for record_id, row in mutation_table.scan()
        if row["score"] is not None and row["score"] >= 10
    )

    assert targets == expected
    assert [row["id"] for _record_id, row in targets] == [2, 3]


def test_collect_returns_empty_snapshot_when_nothing_matches(mutation_table: Table) -> None:
    _insert_rows(mutation_table)

    assert MutationTargetScan(
        mutation_table, ComparisonPredicate("id", "=", 99)
    ).collect() == ()


def test_collect_reuses_null_and_boolean_predicate_semantics(mutation_table: Table) -> None:
    _insert_rows(mutation_table)

    null_rows = MutationTargetScan(mutation_table, IsNullPredicate("score")).collect()
    non_null_rows = MutationTargetScan(
        mutation_table, IsNullPredicate("score", is_not_null=True)
    ).collect()
    composed_rows = MutationTargetScan(
        mutation_table,
        AndPredicate(NotPredicate(IsNullPredicate("score")), ComparisonPredicate("active", "=", True)),
    ).collect()

    assert [row["id"] for _record_id, row in null_rows] == [1, 4]
    assert [row["id"] for _record_id, row in non_null_rows] == [2, 3]
    assert [row["id"] for _record_id, row in composed_rows] == [3]


def test_collect_returns_materialized_snapshot_before_later_table_mutations(mutation_table: Table) -> None:
    rids = _insert_rows(mutation_table)

    targets = MutationTargetScan(mutation_table, ComparisonPredicate("active", "=", True)).collect()
    mutation_table.delete(rids[0])
    mutation_table.insert([5, "epsilon", 30, True])

    assert [record_id for record_id, _row in targets] == [rids[0], rids[2]]
    assert [row["id"] for _record_id, row in targets] == [1, 3]
    assert 5 not in [row["id"] for _record_id, row in targets]


def test_constructor_validates_predicate_against_table_schema(mutation_table: Table) -> None:
    with pytest.raises(ColumnNotFoundError):
        MutationTargetScan(mutation_table, ComparisonPredicate("missing", "=", 1))
