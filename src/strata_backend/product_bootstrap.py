"""Deterministic Phase B product schema and seed bootstrap for Strata."""

from collections.abc import Mapping

from strata_engine import Column, DataType, Schema, StrataEngine
from strata_engine.catalog import IndexAlreadyExistsError, Table


USERS_SCHEMA = Schema([
    Column("id", DataType.BIGINT),
    Column("name", DataType.VARCHAR, max_length=96),
    Column("email", DataType.VARCHAR, max_length=254),
    Column("password_hash", DataType.VARCHAR, nullable=True, max_length=512),
    Column("account_state", DataType.VARCHAR, max_length=24),
    Column("created_at", DataType.BIGINT),
    Column("deleted_at", DataType.BIGINT, nullable=True),
])

WORKSPACES_SCHEMA = Schema([
    Column("id", DataType.BIGINT),
    Column("name", DataType.VARCHAR, max_length=128),
    Column("kind", DataType.VARCHAR, max_length=24),
    Column("created_at", DataType.BIGINT),
    Column("updated_at", DataType.BIGINT),
])

WORKSPACE_MEMBERS_SCHEMA = Schema([
    Column("workspace_id", DataType.BIGINT),
    Column("user_id", DataType.BIGINT),
    Column("role", DataType.VARCHAR, max_length=16),
])

PROJECTS_SCHEMA = Schema([
    Column("id", DataType.BIGINT),
    Column("workspace_id", DataType.BIGINT),
    Column("name", DataType.VARCHAR, max_length=128),
    Column("description", DataType.VARCHAR, nullable=True, max_length=1024),
    Column("created_by_user_id", DataType.BIGINT),
    Column("created_at", DataType.BIGINT),
    Column("updated_at", DataType.BIGINT),
])

TASKS_SCHEMA = Schema([
    Column("id", DataType.BIGINT),
    Column("project_id", DataType.BIGINT),
    Column("title", DataType.VARCHAR, max_length=192),
    Column("description", DataType.VARCHAR, nullable=True, max_length=2048),
    Column("status", DataType.VARCHAR, max_length=24),
    Column("priority", DataType.VARCHAR, max_length=16),
    Column("assignee_user_id", DataType.BIGINT, nullable=True),
    Column("created_by_user_id", DataType.BIGINT),
    Column("created_at", DataType.BIGINT),
    Column("updated_at", DataType.BIGINT),
])

NOTES_SCHEMA = Schema([
    Column("id", DataType.BIGINT),
    Column("task_id", DataType.BIGINT),
    Column("author_user_id", DataType.BIGINT),
    Column("content", DataType.VARCHAR, max_length=3072),
    Column("created_at", DataType.BIGINT),
    Column("updated_at", DataType.BIGINT),
])

PRODUCT_SCHEMAS: Mapping[str, Schema] = {
    "users": USERS_SCHEMA,
    "workspaces": WORKSPACES_SCHEMA,
    "workspace_members": WORKSPACE_MEMBERS_SCHEMA,
    "projects": PROJECTS_SCHEMA,
    "tasks": TASKS_SCHEMA,
    "notes": NOTES_SCHEMA,
}

SEED_TIMESTAMP_MS = 1_700_000_000_000


PRODUCT_SEED: Mapping[str, tuple[tuple[object, ...], ...]] = {
    "users": ((1, "Sithi", "sithi@strata.local", None, "ACTIVE", SEED_TIMESTAMP_MS, None),),
    "workspaces": ((1, "Strata Team", "COLLABORATIVE", SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),),
    "workspace_members": ((1, 1, "OWNER"),),
    "projects": ((1, 1, "Strata", "Build the Strata collaborative project-management system.", 1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),),
    "tasks": (
        (1, 1, "Design application schema", "Define the durable Phase B product tables.", "DONE", "HIGH", 1, 1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
        (2, 1, "Build product backend APIs", "Expose product operations in the next phase.", "TODO", "HIGH", 1, 1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
        (3, 1, "Connect product frontend", None, "TODO", "HIGH", None, 1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
        (4, 1, "Build workspace workflow", "Model the initial workspace collaboration flow.", "IN_PROGRESS", "MEDIUM", 1, 1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
        (5, 1, "Prepare Review 2", None, "TODO", "HIGH", 1, 1, SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
    ),
    "notes": (
        (1, 1, 1, "The initial schema uses BIGINT logical IDs.", SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
        (2, 4, 1, "Keep the DBthon demo isolated from the product database.", SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
        (3, 5, 1, "Review the bootstrap contract before adding APIs.", SEED_TIMESTAMP_MS, SEED_TIMESTAMP_MS),
    ),
}

PRODUCT_INDEXES: Mapping[str, tuple[str, str]] = {
    "users_email_idx": ("users", "email"),
    "workspace_members_workspace_id_idx": ("workspace_members", "workspace_id"),
    "workspace_members_user_id_idx": ("workspace_members", "user_id"),
    "projects_workspace_id_idx": ("projects", "workspace_id"),
    "tasks_project_id_idx": ("tasks", "project_id"),
    "tasks_assignee_user_id_idx": ("tasks", "assignee_user_id"),
    "notes_task_id_idx": ("notes", "task_id"),
}


class ProductBootstrapError(RuntimeError):
    """Raised when an existing product database violates the structural contract."""


def bootstrap_product(engine: StrataEngine) -> None:
    """Initialize product structure and seed only a completely fresh product DB."""
    tables = initialize_product(engine)
    if all(table.count() == 0 for table in tables.values()):
        _insert_seed(tables)


def initialize_product(engine: StrataEngine) -> dict[str, Table]:
    """Create or validate product tables and indexes without changing row data."""
    if not isinstance(engine, StrataEngine):
        raise TypeError(f"Expected StrataEngine, got {type(engine).__name__}.")
    if not engine.is_open:
        raise ProductBootstrapError("Product bootstrap requires an open StrataEngine.")

    tables = _ensure_tables(engine)
    _ensure_indexes(engine, tables)
    return tables


def _ensure_tables(engine: StrataEngine) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for name, expected_schema in PRODUCT_SCHEMAS.items():
        if engine.has_table(name):
            table = engine.get_table(name)
            if table.schema != expected_schema:
                raise ProductBootstrapError(f"Product table '{name}' has an incompatible schema.")
        else:
            table = engine.create_table(name, expected_schema)
        tables[name] = table
    return tables


def _insert_seed(tables: Mapping[str, Table]) -> None:
    for name, rows in PRODUCT_SEED.items():
        for row in rows:
            tables[name].insert(row)


def _ensure_indexes(engine: StrataEngine, tables: Mapping[str, Table]) -> None:
    bindings = {
        index.name.lower(): (table_name, index.column_ordinal)
        for table_name, table in tables.items()
        for index in table.indexes
    }
    for index_name, (table_name, column_name) in PRODUCT_INDEXES.items():
        expected = (table_name, tables[table_name].schema.column_index(column_name))
        actual = bindings.get(index_name.lower())
        if actual is None:
            try:
                engine.create_index(index_name, table_name, column_name)
            except IndexAlreadyExistsError as exc:
                raise ProductBootstrapError(
                    f"Index '{index_name}' already exists outside the expected product binding."
                ) from exc
        elif actual != expected:
            raise ProductBootstrapError(
                f"Index '{index_name}' has an incompatible product table or column target."
            )
