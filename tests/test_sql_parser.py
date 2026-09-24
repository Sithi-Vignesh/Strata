"""Focused syntax and AST-boundary tests for the Phase 8 SQL parser."""

from dataclasses import FrozenInstanceError

import pytest

from strata_engine.sql import (
    AndExpression,
    ColumnList,
    ComparisonExpression,
    CreateTableStatement,
    ColumnDefinition,
    IsNullExpression,
    InsertStatement,
    Lexer,
    NotExpression,
    OrderByItem,
    OrExpression,
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


def test_parser_insert_values_literals_and_optional_semicolon() -> None:
    statement = parse("INSERT INTO users VALUES (1, -2.5, 'O''Brien', TRUE, NULL);")
    assert statement == InsertStatement("users", (1, -2.5, "O'Brien", True, None))
    assert parse("insert into users values (1)") == InsertStatement("users", (1,))


def test_parser_create_table_builds_ordered_syntax_only_columns() -> None:
    statement = parse("""create table Users (
        id integer,
        audit_id bigint,
        score float,
        active boolean,
        name varchar(100)
    );""")
    assert statement == CreateTableStatement(
        "Users",
        (
            ColumnDefinition("id", "INTEGER"),
            ColumnDefinition("audit_id", "BIGINT"),
            ColumnDefinition("score", "FLOAT"),
            ColumnDefinition("active", "BOOLEAN"),
            ColumnDefinition("name", "VARCHAR", 100),
        ),
    )
    assert parse("CREATE TABLE users (id INTEGER)").columns == (ColumnDefinition("id", "INTEGER"),)


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


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users VALUES ()",
        "INSERT INTO users VALUES (1,)",
        "INSERT INTO users VALUES (1), (2)",
        "INSERT INTO users (id) VALUES (1)",
    ],
)
def test_parser_rejects_unsupported_insert_forms(sql: str) -> None:
    with pytest.raises(SQLParseError):
        parse(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t ()",
        "CREATE TABLE t (id INTEGER,)",
        "CREATE TABLE t (id INTEGER name VARCHAR(10))",
        "CREATE TABLE t (name VARCHAR)",
        "CREATE TABLE t (name VARCHAR())",
        "CREATE TABLE t (name VARCHAR(foo))",
        "CREATE TABLE t (id INTEGER(10))",
        "CREATE TABLE t (x UNKNOWN)",
        "CREATE TABLE t (id INTEGER NOT NULL)",
        "CREATE TABLE t (id INTEGER NULL)",
        "CREATE TABLE t (id INTEGER); SELECT * FROM t",
    ],
)
def test_parser_rejects_unsupported_create_table_forms(sql: str) -> None:
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


def test_parser_compound_predicate_ast_shapes_and_precedence() -> None:
    statement = parse("SELECT * FROM users WHERE a = 1 OR b = 2 AND c = 3")
    assert statement.where == OrExpression(
        ComparisonExpression("a", "=", 1),
        AndExpression(ComparisonExpression("b", "=", 2), ComparisonExpression("c", "=", 3)),
    )

    statement = parse("SELECT * FROM users WHERE NOT a = 1 AND b = 2")
    assert statement.where == AndExpression(
        NotExpression(ComparisonExpression("a", "=", 1)), ComparisonExpression("b", "=", 2)
    )


def test_parser_parentheses_not_and_left_associativity() -> None:
    statement = parse("SELECT * FROM users WHERE NOT (a = 1 OR b = 2) AND c = 3")
    assert statement.where == AndExpression(
        NotExpression(
            OrExpression(ComparisonExpression("a", "=", 1), ComparisonExpression("b", "=", 2))
        ),
        ComparisonExpression("c", "=", 3),
    )

    assert parse("SELECT * FROM users WHERE (a = 1 OR b = 2) AND c = 3").where == AndExpression(
        OrExpression(ComparisonExpression("a", "=", 1), ComparisonExpression("b", "=", 2)),
        ComparisonExpression("c", "=", 3),
    )

    assert parse("SELECT * FROM users WHERE a = 1 AND b = 2 AND c = 3").where == AndExpression(
        AndExpression(ComparisonExpression("a", "=", 1), ComparisonExpression("b", "=", 2)),
        ComparisonExpression("c", "=", 3),
    )
    assert parse("SELECT * FROM users WHERE a = 1 OR b = 2 OR c = 3").where == OrExpression(
        OrExpression(ComparisonExpression("a", "=", 1), ComparisonExpression("b", "=", 2)),
        ComparisonExpression("c", "=", 3),
    )


def test_parser_compound_predicates_preserve_is_not_null() -> None:
    assert parse("SELECT * FROM users WHERE nickname IS NOT NULL OR NOT active = TRUE").where == OrExpression(
        IsNullExpression("nickname", True), NotExpression(ComparisonExpression("active", "=", True))
    )
    assert parse("SELECT * FROM users WHERE NOT nickname IS NULL").where == NotExpression(
        IsNullExpression("nickname")
    )


def test_compound_ast_nodes_are_immutable() -> None:
    expression = AndExpression(ComparisonExpression("a", "=", 1), ComparisonExpression("b", "=", 2))
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        expression.left = ComparisonExpression("c", "=", 3)  # type: ignore[misc]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users WHERE AND age = 1",
        "SELECT * FROM users WHERE OR age = 1",
        "SELECT * FROM users WHERE age = 1 AND",
        "SELECT * FROM users WHERE age = 1 OR",
        "SELECT * FROM users WHERE NOT",
        "SELECT * FROM users WHERE ()",
        "SELECT * FROM users WHERE (age = 1",
        "SELECT * FROM users WHERE age = 1)",
        "SELECT * FROM users WHERE (OR age = 1)",
        "SELECT (name) FROM users",
    ],
)
def test_parser_rejects_malformed_compound_predicates(sql: str) -> None:
    with pytest.raises(SQLParseError):
        parse(sql)


def test_parser_order_by_limit_offset_ast_fields() -> None:
    statement = parse(
        "SELECT name FROM users WHERE active = TRUE ORDER BY age, name ASC, id DESC LIMIT 5 OFFSET 2;"
    )
    assert statement.order_by == (
        OrderByItem("age"),
        OrderByItem("name"),
        OrderByItem("id", True),
    )
    assert statement.limit == 5
    assert statement.offset == 2
    assert parse("SELECT * FROM users LIMIT 0").limit == 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users OFFSET 1",
        "SELECT * FROM users LIMIT 5 ORDER BY age",
        "SELECT * FROM users ORDER BY age WHERE active = TRUE",
        "SELECT * FROM users LIMIT 5 WHERE active = TRUE",
        "SELECT * FROM users ORDER",
        "SELECT * FROM users ORDER age",
        "SELECT * FROM users ORDER BY",
        "SELECT * FROM users ORDER BY age,",
        "SELECT * FROM users ORDER BY , age",
        "SELECT * FROM users ORDER BY age,,name",
        "SELECT * FROM users ORDER BY age ASC DESC",
        "SELECT * FROM users LIMIT",
        "SELECT * FROM users LIMIT -1",
        "SELECT * FROM users LIMIT 1.5",
        "SELECT * FROM users LIMIT TRUE",
        "SELECT * FROM users LIMIT 1 OFFSET",
        "SELECT * FROM users LIMIT 1 OFFSET -1",
        "SELECT * FROM users LIMIT 1 OFFSET 1.5",
    ],
)
def test_parser_rejects_invalid_ordering_and_limit_syntax(sql: str) -> None:
    with pytest.raises(SQLParseError):
        parse(sql)
