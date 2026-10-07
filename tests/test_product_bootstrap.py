"""Phase B1 product-bootstrap coverage."""

from pathlib import Path

import pytest

from strata_backend.product_bootstrap import (
    PRODUCT_INDEXES,
    PRODUCT_SCHEMAS,
    PRODUCT_SEED,
    ProductBootstrapError,
    SEED_TIMESTAMP_MS,
    bootstrap_product,
    initialize_product,
)
from strata_engine import Column, DataType, Schema, StrataEngine


def _rows(engine: StrataEngine, table_name: str) -> tuple[tuple[object, ...], ...]:
    return tuple(row.values for _, row in engine.get_table(table_name).scan())


def _indexed_rows(engine: StrataEngine, table_name: str, column_name: str, value: object) -> tuple[tuple[object, ...], ...]:
    table = engine.get_table(table_name)
    index = table.index_for_column(column_name)
    assert index is not None
    return tuple(table.get(record_id).values for record_id in index.tree.search(value))


def test_product_bootstrap_creates_exact_schema_seed_and_indexes(tmp_path: Path) -> None:
    with StrataEngine(tmp_path / "strata") as engine:
        bootstrap_product(engine)

        assert engine.list_tables() == list(PRODUCT_SCHEMAS)
        for name, schema in PRODUCT_SCHEMAS.items():
            assert engine.get_table(name).schema == schema
            assert _rows(engine, name) == PRODUCT_SEED[name]

        tasks = engine.get_table("tasks")
        assert any(row[3] is None for _, row in tasks.scan())
        assert any(row[6] is None for _, row in tasks.scan())
        assert _rows(engine, "users")[0][4:] == ("ACTIVE", SEED_TIMESTAMP_MS, None)
        assert _rows(engine, "workspaces")[0][2:] == ("COLLABORATIVE", SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS)
        assert _rows(engine, "projects")[0][4:] == (1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS)
        assert all(row.values[7:] == (1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS) for _, row in tasks.scan())
        assert all(row.values[4:] == (SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS) for _, row in engine.get_table("notes").scan())
        assert _rows(engine, "sessions") == ()

        actual_indexes = {
            index.name: (table_name, engine.get_table(table_name).schema[index.column_ordinal].name)
            for table_name in PRODUCT_SCHEMAS
            for index in engine.get_table(table_name).indexes
        }
        assert actual_indexes == PRODUCT_INDEXES

        users = {row[0] for _, row in engine.get_table("users").scan()}
        workspaces = {row[0] for _, row in engine.get_table("workspaces").scan()}
        projects = {row[0] for _, row in engine.get_table("projects").scan()}
        tasks_by_id = {row[0] for _, row in tasks.scan()}
        assert all(row[0] in workspaces and row[1] in users for _, row in engine.get_table("workspace_members").scan())
        assert all(row[1] in workspaces and row[4] in users for _, row in engine.get_table("projects").scan())
        assert all(row[1] in projects and (row[6] is None or row[6] in users) and row[7] in users for _, row in tasks.scan())
        assert all(row[1] in tasks_by_id and row[2] in users for _, row in engine.get_table("notes").scan())
        assert engine.get_table("sessions").schema == PRODUCT_SCHEMAS["sessions"]
        assert engine.get_table("sessions").index_for_column("token_digest") is not None
        assert engine.get_table("sessions").index_for_column("user_id") is not None


def test_product_bootstrap_is_idempotent_and_indexes_support_product_lookups(tmp_path: Path) -> None:
    with StrataEngine(tmp_path / "strata") as engine:
        bootstrap_product(engine)
        before = {name: _rows(engine, name) for name in PRODUCT_SCHEMAS}
        bootstrap_product(engine)

        assert {name: _rows(engine, name) for name in PRODUCT_SCHEMAS} == before
        assert _indexed_rows(engine, "projects", "workspace_id", 1) == PRODUCT_SEED["projects"]
        assert _indexed_rows(engine, "tasks", "project_id", 1) == PRODUCT_SEED["tasks"]
        assert _indexed_rows(engine, "notes", "task_id", 1) == (PRODUCT_SEED["notes"][0],)


def test_product_bootstrap_reopens_with_seed_nulls_and_indexes(tmp_path: Path) -> None:
    database = tmp_path / "strata"
    with StrataEngine(database) as engine:
        bootstrap_product(engine)

    with StrataEngine(database) as engine:
        bootstrap_product(engine)
        assert _rows(engine, "tasks") == PRODUCT_SEED["tasks"]
        assert {index.name for table_name in PRODUCT_SCHEMAS for index in engine.get_table(table_name).indexes} == set(PRODUCT_INDEXES)


def test_structural_initialization_keeps_empty_and_populated_rows_unchanged(tmp_path: Path) -> None:
    database = tmp_path / "strata"
    with StrataEngine(database) as engine:
        initialize_product(engine)
        assert all(engine.get_table(name).count() == 0 for name in PRODUCT_SCHEMAS)
        engine.get_table("users").insert(
            (99, "Existing", "existing@strata.local", None, "ACTIVE", SEED_TIMESTAMP_MS, None)
        )
        initialize_product(engine)
        assert _rows(engine, "users") == (
            (99, "Existing", "existing@strata.local", None, "ACTIVE", SEED_TIMESTAMP_MS, None),
        )
        bootstrap_product(engine)
        assert _rows(engine, "users") == (
            (99, "Existing", "existing@strata.local", None, "ACTIVE", SEED_TIMESTAMP_MS, None),
        )


def test_product_bootstrap_rejects_schema_mismatch(tmp_path: Path) -> None:
    with StrataEngine(tmp_path / "strata") as engine:
        engine.create_table("users", Schema([Column("id", DataType.INTEGER)]))
        with pytest.raises(ProductBootstrapError, match="users.*incompatible schema"):
            bootstrap_product(engine)


def test_product_bootstrap_does_not_repair_partial_product_data(tmp_path: Path) -> None:
    with StrataEngine(tmp_path / "strata") as engine:
        for name, schema in PRODUCT_SCHEMAS.items():
            engine.create_table(name, schema)
        engine.get_table("users").insert(PRODUCT_SEED["users"][0])

        bootstrap_product(engine)
        assert _rows(engine, "users") == PRODUCT_SEED["users"]
        assert all(engine.get_table(name).count() == 0 for name in PRODUCT_SCHEMAS if name != "users")


def test_product_bootstrap_rejects_wrong_named_index_target(tmp_path: Path) -> None:
    with StrataEngine(tmp_path / "strata") as engine:
        for name, schema in PRODUCT_SCHEMAS.items():
            engine.create_table(name, schema)
        engine.create_index("users_email_idx", "users", "id")

        with pytest.raises(ProductBootstrapError, match="users_email_idx.*incompatible"):
            bootstrap_product(engine)
