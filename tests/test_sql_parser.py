"""Focused syntax and AST-boundary tests for the Phase 8 SQL parser."""

from dataclasses import FrozenInstanceError

import pytest

from strata_engine.sql import (
    ColumnList,
    ComparisonExpression,
    IsNullExpression,
    Lexer,
    Parser,
    SQLParseError,
    SelectAll,
)


def parse(sql: str):
    return Parser(Lexer(sql).tokenize()).parse()


def test_parser_select_all_with_optional_semicolon_and_preserved_identifier() -> None:
    statement = parse("SeLeCt * FrOm Users;")
    assert statement.table_name == "Users"
    assert isinstance(statement.projection, SelectAll)
    assert statement.where is None


def test_parser_column_list_comparison_and_scalar_values() -> None:
    statement = parse("SELECT Name, age FROM users WHERE age >= -2.5")
    assert statement.projection == ColumnList(("Name", "age"))
    assert statement.where == ComparisonExpression("age", ">=", -2.5)


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("=", "="), ("==", "="), ("!=", "!="), ("<>", "!="), ("<", "<"), ("<=", "<="), (">", ">"), (">=", ">=")],
)
def test_parser_normalizes_all_comparison_operators(operator: str, expected: str) -> None:
    statement = parse(f"SELECT * FROM users WHERE age {operator} 18")
    assert statement.where == ComparisonExpression("age", expected, 18)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT name FROM users WHERE nickname IS NULL", IsNullExpression("nickname")),
        ("SELECT name\nFROM users\nWHERE nickname IS NOT NULL;", IsNullExpression("nickname", True)),
        ("SELECT name FROM users WHERE active = TRUE", ComparisonExpression("active", "=", True)),
        ("SELECT name FROM users WHERE name = 'O''Brien'", ComparisonExpression("name", "=", "O'Brien")),
    ],
)
def test_parser_where_forms(sql: str, expected: object) -> None:
    assert parse(sql).where == expected


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT FROM users",
        "SELECT name, FROM users",
        "SELECT , name FROM users",
        "SELECT name users",
        "SELECT name FROM",
        "SELECT * FROM users WHERE",
        "SELECT * FROM users WHERE age LIKE 1",
        "SELECT * FROM users WHERE age = NULL",
        "SELECT * FROM users;;",
        "SELECT * FROM users; SELECT * FROM tasks",
    ],
)
def test_parser_rejects_syntax_outside_the_locked_grammar(sql: str) -> None:
    with pytest.raises(SQLParseError):
        parse(sql)


def test_parser_leaves_names_unresolved_and_ast_is_immutable() -> None:
    statement = parse("SELECT missing, MISSING FROM nonexistent_table")
    assert statement.table_name == "nonexistent_table"
    assert statement.projection == ColumnList(("missing", "MISSING"))
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        statement.table_name = "other"  # type: ignore[misc]
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        statement.projection.columns = ()  # type: ignore[misc]

    comparison = ComparisonExpression("age", "=", 18)
    null_check = IsNullExpression("nickname")
    select_all = SelectAll()
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        comparison.operator = ">"  # type: ignore[misc]
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        null_check.is_not_null = True  # type: ignore[misc]
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        select_all.extra = True  # type: ignore[misc]


def test_column_list_normalizes_mutable_sequence() -> None:
    columns = ["name", "age"]
    projection = ColumnList(columns)  # type: ignore[arg-type]
    columns[:] = ["id"]
    assert projection.columns == ("name", "age")
