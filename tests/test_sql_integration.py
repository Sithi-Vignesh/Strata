"""End-to-end SQL frontend integration through existing planner and operators."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog, Table
from strata_engine.planning import Planner
from strata_engine.schema import Column, DataType, Schema
from strata_engine.sql import Binder, Lexer, Parser


def execute(catalog: Catalog, sql: str) -> list[tuple[object, ...]]:
    statement = Parser(Lexer(sql).tokenize()).parse()
    request = Binder(catalog).bind(statement)
    plan = Planner().plan(request)
    operator = plan.create_operator()
    with operator:
        return [row.values for row in operator]


@pytest.fixture
def populated_catalog(tmp_path: Path):
    cat = Catalog(tmp_path / "database")
    table = cat.create_table(
        "users",
        Schema([
            Column("id", DataType.INTEGER, nullable=False),
            Column("name", DataType.VARCHAR, nullable=False, max_length=32),
            Column("age", DataType.INTEGER, nullable=False),
            Column("nickname", DataType.VARCHAR, nullable=True, max_length=32),
            Column("active", DataType.BOOLEAN, nullable=False),
        ]),
    )
    table.insert([1, "Alice", 20, None, True])
    table.insert([2, "Bob", 16, "Bobby", False])
    table.insert([3, "Carol", 24, "", True])
    yield cat, table
    cat.close()


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT * FROM users;", [(1, "Alice", 20, None, True), (2, "Bob", 16, "Bobby", False), (3, "Carol", 24, "", True)]),
        ("SELECT name, age FROM users;", [("Alice", 20), ("Bob", 16), ("Carol", 24)]),
        ("SELECT * FROM users WHERE age >= 18;", [(1, "Alice", 20, None, True), (3, "Carol", 24, "", True)]),
        ("SELECT name, age FROM users WHERE age >= 18;", [("Alice", 20), ("Carol", 24)]),
        ("SELECT name FROM users WHERE nickname IS NULL;", [("Alice",)]),
        ("SELECT name FROM users WHERE nickname IS NOT NULL;", [("Bob",), ("Carol",)]),
        ("SELECT name FROM users WHERE active = TRUE;", [("Alice",), ("Carol",)]),
        ("SELECT name FROM users WHERE name = 'Alice';", [("Alice",)]),
        (
            "SELECT name FROM users WHERE age >= 18 AND active = TRUE;",
            [("Alice",), ("Carol",)],
        ),
        ("SELECT name FROM users WHERE age < 18 OR age >= 65;", [("Bob",)]),
        ("SELECT name FROM users WHERE NOT active = TRUE;", [("Bob",)]),
        (
            "SELECT name FROM users WHERE nickname IS NULL OR active = FALSE;",
            [("Alice",), ("Bob",)],
        ),
        (
            "SELECT name FROM users WHERE age < 18 OR active = TRUE AND nickname IS NULL;",
            [("Alice",), ("Bob",)],
        ),
        (
            "SELECT name FROM users WHERE (age < 18 OR active = TRUE) AND nickname IS NULL;",
            [("Alice",)],
        ),
    ],
)
def test_sql_pipeline_executes_through_planner(populated_catalog, sql: str, expected) -> None:
    catalog, _ = populated_catalog
    assert execute(catalog, sql) == expected


def test_sql_frontend_binding_and_planning_do_not_scan_before_execution(populated_catalog, monkeypatch) -> None:
    catalog, _ = populated_catalog

    def fail_scan(self):
        raise AssertionError("no scan before operator execution")

    monkeypatch.setattr(Table, "scan", fail_scan)
    statement = Parser(Lexer("SELECT name FROM users WHERE age >= 18").tokenize()).parse()
    request = Binder(catalog).bind(statement)
    plan = Planner().plan(request)
    assert plan.schema.column_names == ("name",)


def test_sql_and_root_public_api_exports() -> None:
    from strata_engine import Binder as RootBinder
    from strata_engine import Lexer as RootLexer
    from strata_engine import Parser as RootParser
    from strata_engine import SQLBindingError, SQLError, SQLLexError, SQLParseError
    from strata_engine.sql import Binder, Lexer, Parser

    assert (RootLexer, RootParser, RootBinder) == (Lexer, Parser, Binder)
    assert issubclass(SQLLexError, SQLError)
    assert issubclass(SQLParseError, SQLError)
    assert issubclass(SQLBindingError, SQLError)
