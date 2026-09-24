"""Unit tests for the strata_engine package.

Validates the public engine facade:
- Successful import and initialization
- Handling of optional data directory paths without touching disk
- Deterministic status reporting
- Interface placeholder for SQL execution raising NotImplementedError
"""

from pathlib import Path
import pytest
from strata_engine import Column, DataType, QueryResult, Schema, StrataEngine, Tuple


def test_engine_import() -> None:
    """Verify StrataEngine can be imported from strata_engine."""
    from strata_engine.engine import StrataEngine as DirectStrataEngine

    assert StrataEngine is DirectStrataEngine


def test_engine_initialization_default() -> None:
    """Verify StrataEngine initializes cleanly with default arguments."""
    engine = StrataEngine()
    assert engine.is_initialized is True
    assert engine.data_dir is None


def test_engine_initialization_with_custom_path() -> None:
    """Verify StrataEngine accepts and normalizes an optional data directory."""
    test_path_str = "custom_data_dir"
    engine_from_str = StrataEngine(data_dir=test_path_str)
    assert engine_from_str.data_dir == Path(test_path_str)

    test_path_obj = Path("another_data_dir")
    engine_from_path = StrataEngine(data_dir=test_path_obj)
    assert engine_from_path.data_dir == test_path_obj


def test_engine_status_structure_and_values() -> None:
    """Verify status method returns deterministic, expected structure and keys."""
    engine = StrataEngine(data_dir="runtime_data")
    status = engine.status()

    assert isinstance(status, dict)
    assert status["name"] == "StrataEngine"
    assert status["status"] == "initialized"
    assert status["initialized"] is True
    assert status["data_dir"] == "runtime_data"


def test_engine_status_determinism() -> None:
    """Verify repeated status calls yield identical results."""
    engine = StrataEngine()
    first_call = engine.status()
    second_call = engine.status()

    assert first_call == second_call
    assert first_call == {
        "name": "StrataEngine",
        "status": "initialized",
        "initialized": True,
        "data_dir": None,
    }


def test_engine_execute_requires_an_open_engine(tmp_path: Path) -> None:
    """Verify SQL execution follows the established catalog lifecycle."""
    from strata_engine.storage import StorageClosedError

    with pytest.raises(StorageClosedError):
        StrataEngine(tmp_path).execute("SELECT * FROM users")


# ============================================================================
# Phase 5: Engine Lifecycle & Table Access Tests
# ============================================================================


def test_engine_lifecycle_open_close(tmp_path: Path) -> None:
    """Verify open and close lifecycle transitions and status reporting."""
    from strata_engine.storage import StorageClosedError

    engine = StrataEngine(data_dir=tmp_path)
    assert engine.is_open is False
    assert engine.status()["status"] == "initialized"

    engine.open()
    assert engine.is_open is True
    assert engine.status()["status"] == "open"
    assert engine.catalog is not None

    # Redundant open is a safe no-op
    engine.open()
    assert engine.is_open is True

    engine.close()
    assert engine.is_open is False
    assert engine.status()["status"] == "initialized"

    with pytest.raises(StorageClosedError):
        _ = engine.catalog


def test_engine_open_without_data_dir_raises() -> None:
    """Verify opening StrataEngine without a configured data_dir raises StorageClosedError."""
    from strata_engine.storage import StorageClosedError

    engine = StrataEngine()
    with pytest.raises(StorageClosedError) as exc_info:
        engine.open()
    assert "without a configured data_dir" in str(exc_info.value)


def test_engine_context_manager(tmp_path: Path) -> None:
    """Verify StrataEngine context manager opens on enter and closes on exit."""
    from strata_engine.schema import Column, DataType, Schema

    schema = Schema([Column("id", DataType.INTEGER, nullable=False)])

    with StrataEngine(data_dir=tmp_path) as engine:
        assert engine.is_open is True
        tbl = engine.create_table("items", schema)
        rid = tbl.insert([42])
        assert tbl.get(rid)["id"] == 42
        assert engine.list_tables() == ["items"]

    assert engine.is_open is False


def test_engine_table_delegators_and_persistence(tmp_path: Path) -> None:
    """Verify engine table management and persistence across restart."""
    from strata_engine.schema import Column, DataType, Schema

    schema = Schema([
        Column("id", DataType.INTEGER, nullable=False),
        Column("name", DataType.VARCHAR, nullable=False, max_length=50),
    ])

    # Session 1
    with StrataEngine(data_dir=tmp_path) as engine:
        tbl = engine.create_table("users", schema)
        tbl.insert([1, "Alice"])
        tbl.insert([2, "Bob"])

        assert engine.has_table("users") is True
        assert engine.has_table("nonexistent") is False
        assert engine.list_tables() == ["users"]

    # Session 2
    with StrataEngine(data_dir=tmp_path) as engine:
        assert engine.has_table("users") is True
        assert engine.list_tables() == ["users"]

        tbl_recovered = engine.get_table("users")
        assert tbl_recovered.count() == 2
        rows = [r.values for _, r in tbl_recovered.scan()]
        assert rows == [(1, "Alice"), (2, "Bob")]

        engine.drop_table("users")
        assert engine.has_table("users") is False
        assert engine.list_tables() == []


def test_engine_operations_closed_error(tmp_path: Path) -> None:
    """Verify engine table operations raise StorageClosedError when unopened."""
    from strata_engine.schema import Column, DataType, Schema
    from strata_engine.storage import StorageClosedError

    schema = Schema([Column("id", DataType.INTEGER)])
    engine = StrataEngine(data_dir=tmp_path)

    with pytest.raises(StorageClosedError):
        engine.create_table("test", schema)
    with pytest.raises(StorageClosedError):
        engine.get_table("test")
    with pytest.raises(StorageClosedError):
        engine.drop_table("test")
    with pytest.raises(StorageClosedError):
        engine.list_tables()


# ============================================================================
# Phase 15: Engine SQL Integration
# ============================================================================


@pytest.fixture
def sql_engine(tmp_path: Path):
    with StrataEngine(tmp_path / "database") as engine:
        users = engine.create_table(
            "users",
            Schema([
                Column("id", DataType.INTEGER),
                Column("name", DataType.VARCHAR, max_length=20),
                Column("country", DataType.VARCHAR, nullable=True, max_length=8),
            ]),
        )
        orders = engine.create_table(
            "orders",
            Schema([
                Column("id", DataType.INTEGER),
                Column("user_id", DataType.INTEGER),
                Column("total", DataType.INTEGER),
            ]),
        )
        users.insert([1, "Ada", "IN"]); users.insert([2, "Ben", "US"]); users.insert([3, "Cal", "IN"])
        orders.insert([10, 1, 100]); orders.insert([11, 1, 50]); orders.insert([12, 2, 200])
        yield engine


def test_engine_execute_materializes_select_projection_order_and_empty_result(sql_engine: StrataEngine) -> None:
    result = sql_engine.execute("SELECT name FROM users ORDER BY id DESC LIMIT 2 OFFSET 1")
    assert isinstance(result, QueryResult)
    assert result.schema.column_names == ("name",)
    assert all(isinstance(row, Tuple) for row in result.rows)
    assert [row.values for row in result.rows] == [("Ben",), ("Ada",)]
    assert sql_engine.execute("SELECT name FROM users WHERE id > 99").rows == ()


def test_engine_execute_aggregates_groups_joins_and_preserves_public_schema(sql_engine: StrataEngine) -> None:
    count = sql_engine.execute("SELECT COUNT(*) FROM users")
    assert count.schema.column_names == ("count_star",)
    assert [row.values for row in count.rows] == [(3,)]

    grouped = sql_engine.execute("SELECT country, COUNT(*) FROM users GROUP BY country ORDER BY count_star DESC, country")
    assert grouped.schema.column_names == ("country", "count_star")
    assert [row.values for row in grouped.rows] == [("IN", 2), ("US", 1)]

    joined = sql_engine.execute("SELECT users.name, orders.total FROM users JOIN orders ON users.id = orders.user_id ORDER BY orders.id")
    assert joined.schema.column_names == ("name", "total")
    assert all(not name.startswith("_j_") for name in joined.schema.column_names)
    assert [row.values for row in joined.rows] == [("Ada", 100), ("Ada", 50), ("Ben", 200)]

    joined_grouped = sql_engine.execute("SELECT users.country, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id GROUP BY users.country ORDER BY count_star DESC")
    assert joined_grouped.schema.column_names == ("country", "count_star")
    assert [row.values for row in joined_grouped.rows] == [("IN", 2), ("US", 1)]


def test_engine_execute_propagates_existing_errors_and_query_result_is_immutable(sql_engine: StrataEngine) -> None:
    from dataclasses import FrozenInstanceError
    from strata_engine.catalog import TableNotFoundError
    from strata_engine.schema import ColumnNotFoundError
    from strata_engine.sql import SQLParseError

    with pytest.raises(SQLParseError):
        sql_engine.execute("SELECT FROM users")
    with pytest.raises(TableNotFoundError):
        sql_engine.execute("SELECT * FROM missing")
    with pytest.raises(ColumnNotFoundError):
        sql_engine.execute("SELECT missing FROM users")

    result = sql_engine.execute("SELECT name FROM users ORDER BY id LIMIT 1")
    with pytest.raises(FrozenInstanceError):
        result.rows = ()  # type: ignore[misc]
    assert result.rows[0].values == ("Ada",)
