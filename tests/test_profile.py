"""Focused Phase 21B.1 engine query-profiling coverage."""

from pathlib import Path

import pytest

from strata_engine import (
    CommandResult,
    Column,
    DataType,
    IndexScanMetrics,
    ProfiledExecutionResult,
    QueryResult,
    Schema,
    StrataEngine,
    TableScanMetrics,
)
from strata_engine.sql import SQLParseError


@pytest.fixture
def profiled_engine(tmp_path: Path):
    with StrataEngine(tmp_path / "database") as engine:
        tasks = engine.create_table(
            "tasks",
            Schema([
                Column("id", DataType.INTEGER),
                Column("status", DataType.VARCHAR, max_length=16),
                Column("priority", DataType.INTEGER),
            ]),
        )
        tasks.insert([1, "OPEN", 1])
        tasks.insert([2, "OPEN", 2])
        tasks.insert([3, "CLOSED", 3])
        tasks.insert([4, "CLOSED", 4])
        engine.create_index("tasks_status_idx", "tasks", "status")

        orders = engine.create_table(
            "orders",
            Schema([Column("id", DataType.INTEGER), Column("task_id", DataType.INTEGER)]),
        )
        orders.insert([10, 1])
        yield engine


def test_profiled_table_scan_and_execute_regression(profiled_engine: StrataEngine) -> None:
    profiled = profiled_engine.execute_profiled("SELECT id FROM tasks WHERE priority > 2")

    assert isinstance(profiled, ProfiledExecutionResult)
    assert isinstance(profiled.result, QueryResult)
    assert [row.values for row in profiled.result.rows] == [(3,), (4,)]
    assert profiled.profile is not None
    assert profiled.profile.access_path == "TableScan"
    assert profiled.profile.table_name == "tasks"
    assert profiled.profile.index_name is None
    assert profiled.profile.condition is None
    assert profiled.profile.metrics == TableScanMetrics(tuples_examined=4)

    normal = profiled_engine.execute("SELECT id FROM tasks WHERE priority > 2")
    assert isinstance(normal, QueryResult)
    assert not hasattr(normal, "profile")


def test_profiled_index_scan_uses_resolved_metadata_and_native_literal(profiled_engine: StrataEngine) -> None:
    profiled = profiled_engine.execute_profiled("SELECT id FROM tasks WHERE status = 'OPEN'")

    assert [row.values for row in profiled.result.rows] == [(1,), (2,)]
    assert profiled.profile is not None
    assert profiled.profile.access_path == "IndexScan"
    assert profiled.profile.table_name == "tasks"
    assert profiled.profile.index_name == "tasks_status_idx"
    assert profiled.profile.condition is not None
    assert (
        profiled.profile.condition.column_name,
        profiled.profile.condition.operator,
        profiled.profile.condition.literal,
    ) == ("status", "=", "OPEN")
    assert isinstance(profiled.profile.metrics, IndexScanMetrics)
    assert profiled.profile.metrics.rids_selected == 2
    assert profiled.profile.metrics.rows_fetched == 2
    assert profiled.profile.metrics.tree_pages_visited >= 1
    assert profiled.profile.metrics.leaf_entries_examined >= 2


def test_profiled_index_scan_distinguishes_candidates_final_rows_and_repeat_reset(profiled_engine: StrataEngine) -> None:
    sql = "SELECT id FROM tasks WHERE status = 'OPEN' AND priority = 2"
    first = profiled_engine.execute_profiled(sql)
    second = profiled_engine.execute_profiled(sql)

    assert [row.values for row in first.result.rows] == [(2,)]
    assert len(first.result.rows) == 1
    assert first.profile is not None
    assert isinstance(first.profile.metrics, IndexScanMetrics)
    assert first.profile.metrics.rids_selected == 2
    assert first.profile.metrics.rows_fetched == 2
    assert second.profile == first.profile


def test_profiled_limit_reports_actual_table_scan_consumption(profiled_engine: StrataEngine) -> None:
    profiled = profiled_engine.execute_profiled(
        "SELECT id FROM tasks WHERE priority > 1 LIMIT 1"
    )

    assert [row.values for row in profiled.result.rows] == [(2,)]
    assert len(profiled.result.rows) == 1
    assert profiled.profile is not None
    assert profiled.profile.metrics == TableScanMetrics(tuples_examined=2)


def test_profiled_filtered_aggregate_reports_underlying_index_scan(profiled_engine: StrataEngine) -> None:
    profiled = profiled_engine.execute_profiled(
        "SELECT COUNT(*) FROM tasks WHERE status = 'OPEN'"
    )

    assert [row.values for row in profiled.result.rows] == [(2,)]
    assert profiled.profile is not None
    assert profiled.profile.access_path == "IndexScan"
    assert isinstance(profiled.profile.metrics, IndexScanMetrics)
    assert profiled.profile.metrics.rids_selected == 2


def test_profiled_commands_and_joins_have_no_singular_profile(profiled_engine: StrataEngine) -> None:
    command = profiled_engine.execute_profiled("INSERT INTO tasks VALUES (5, 'OPEN', 5)")
    assert command.result == CommandResult(affected_rows=1)
    assert command.profile is None

    joined = profiled_engine.execute_profiled(
        "SELECT tasks.id, orders.id FROM tasks JOIN orders ON tasks.id = orders.task_id"
    )
    assert isinstance(joined.result, QueryResult)
    assert [row.values for row in joined.result.rows] == [(1, 10)]
    assert joined.profile is None


def test_profiled_fallback_and_error_propagation(profiled_engine: StrataEngine) -> None:
    fallback = profiled_engine.execute_profiled("SELECT id FROM tasks WHERE status != 'OPEN'")
    assert fallback.profile is not None
    assert fallback.profile.access_path == "TableScan"

    with pytest.raises(SQLParseError):
        profiled_engine.execute_profiled("SELECT FROM tasks")
