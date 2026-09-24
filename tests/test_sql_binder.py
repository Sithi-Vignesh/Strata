"""Binding and validation-boundary tests for the Phase 8 SQL frontend."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog, Table, TableNotFoundError
from strata_engine.commands import InsertCommand
from strata_engine.execution import (
    AndPredicate,
    ComparisonPredicate,
    IsNullPredicate,
    NotPredicate,
    OrPredicate,
)
from strata_engine.planning import OrderBy, Planner
from strata_engine.schema import (
    Column,
    ColumnNotFoundError,
    DataType,
    DuplicateColumnError,
    Schema,
    TypeMismatchError,
)
from strata_engine.sql import Binder, Lexer, Parser, SQLBindingError
from strata_engine.sql.ast import InsertStatement, SQLPredicate, SelectAll, SelectStatement
from strata_engine.storage import StorageClosedError


def bind(catalog: Catalog, sql: str):
    return Binder(catalog).bind(Parser(Lexer(sql).tokenize()).parse())


@pytest.fixture
def catalog(tmp_path: Path):
    cat = Catalog(tmp_path / "database")
    table = cat.create_table(
        "Users",
        Schema([
            Column("id", DataType.INTEGER, nullable=False),
            Column("name", DataType.VARCHAR, nullable=False, max_length=32),
            Column("age", DataType.INTEGER, nullable=False),
            Column("nickname", DataType.VARCHAR, nullable=True, max_length=32),
        ]),
    )
    yield cat, table
    cat.close()


def test_binder_resolves_cached_table_and_translates_projection(catalog) -> None:
    cat, table = catalog
    request = bind(cat, "SELECT Name, age FROM users")
    assert request.table is table is cat.get_table("USERS")
    assert request.projection == ("Name", "age")
    assert request.predicate is None


def test_binder_resolves_insert_target_without_revalidating_values(catalog) -> None:
    cat, table = catalog
    command = Binder(cat).bind(InsertStatement("users", (1, "Ada", 20, None)))
    assert isinstance(command, InsertCommand)
    assert command.table is table
    assert command.values == (1, "Ada", 20, None)

    with pytest.raises(TableNotFoundError):
        Binder(cat).bind(InsertStatement("missing", (1,)))


def test_binder_translates_existing_predicate_types(catalog) -> None:
    cat, _ = catalog
    comparison = bind(cat, "SELECT * FROM users WHERE age >= 18")
    assert comparison.projection is None
    assert isinstance(comparison.predicate, ComparisonPredicate)
    assert comparison.predicate.column_name == "age"
    assert comparison.predicate.op == ">="
    assert comparison.predicate.literal == 18

    is_null = bind(cat, "SELECT * FROM users WHERE nickname IS NULL")
    assert isinstance(is_null.predicate, IsNullPredicate)
    assert is_null.predicate.is_not_null is False

    is_not_null = bind(cat, "SELECT * FROM users WHERE nickname IS NOT NULL")
    assert isinstance(is_not_null.predicate, IsNullPredicate)
    assert is_not_null.predicate.is_not_null is True


def test_binder_propagates_catalog_errors_and_borrows_resources(catalog, monkeypatch) -> None:
    cat, table = catalog
    with pytest.raises(TableNotFoundError):
        bind(cat, "SELECT * FROM absent")

    def fail_scan(self):
        raise AssertionError("binding must not scan")

    monkeypatch.setattr(Table, "scan", fail_scan)
    request = bind(cat, "SELECT * FROM users")
    assert request.table is table
    assert table.is_closed is False
    assert cat.is_closed is False


def test_binder_propagates_closed_catalog_error(catalog) -> None:
    cat, _ = catalog
    cat.close()
    with pytest.raises(StorageClosedError):
        bind(cat, "SELECT * FROM users")


def test_binder_preserves_existing_planning_validation_boundaries(catalog) -> None:
    cat, _ = catalog
    missing_projection = bind(cat, "SELECT missing FROM users")
    with pytest.raises(ColumnNotFoundError):
        Planner().plan(missing_projection)

    duplicate_projection = bind(cat, "SELECT name, NAME FROM users")
    with pytest.raises(DuplicateColumnError):
        Planner().plan(duplicate_projection)

    incompatible_literal = bind(cat, "SELECT * FROM users WHERE age = 'abc'")
    with pytest.raises(TypeMismatchError):
        Planner().plan(incompatible_literal)


def test_binder_recursively_translates_compound_predicates(catalog) -> None:
    cat, _ = catalog
    request = bind(
        cat,
        "SELECT * FROM users WHERE NOT (age >= 18 AND (nickname IS NULL OR age < 65))",
    )

    assert isinstance(request.predicate, NotPredicate)
    assert isinstance(request.predicate.child, AndPredicate)
    assert isinstance(request.predicate.child.left, ComparisonPredicate)
    assert isinstance(request.predicate.child.right, OrPredicate)
    assert isinstance(request.predicate.child.right.left, IsNullPredicate)
    assert isinstance(request.predicate.child.right.right, ComparisonPredicate)


def test_binder_rejects_unsupported_sql_predicate_nodes(catalog) -> None:
    class UnsupportedPredicate(SQLPredicate):
        pass

    cat, _ = catalog
    statement = SelectStatement("users", SelectAll(), UnsupportedPredicate())
    with pytest.raises(SQLBindingError, match="Unsupported SQL predicate node"):
        Binder(cat).bind(statement)


def test_binder_translates_ordering_and_defers_order_column_validation(catalog) -> None:
    cat, _ = catalog
    request = bind(
        cat,
        "SELECT name FROM users WHERE age >= 18 ORDER BY missing, age DESC LIMIT 3 OFFSET 1",
    )
    assert request.order_by == (OrderBy("missing"), OrderBy("age", True))
    assert request.limit == 3
    assert request.offset == 1
    with pytest.raises(ColumnNotFoundError):
        Planner().plan(request)
