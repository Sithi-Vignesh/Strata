"""End-to-end coverage for minimal SQL DELETE support."""

from pathlib import Path

import pytest

from strata_engine import CommandResult, QueryResult, StrataEngine
from strata_engine.catalog import TableNotFoundError
from strata_engine.commands import DeleteCommand
from strata_engine.schema import Column, ColumnNotFoundError, DataType, Schema, TypeMismatchError
from strata_engine.sql import Binder, Lexer, Parser, SQLParseError
from strata_engine.sql.ast import AndExpression, ComparisonExpression, DeleteStatement, IsNullExpression
from strata_engine.sql.token import TokenType
from strata_engine.storage import RecordNotFoundError


def _parse(sql: str):
    return Parser(Lexer(sql).tokenize()).parse()


@pytest.fixture
def delete_engine(tmp_path: Path):
    with StrataEngine(tmp_path / "database") as engine:
        table = engine.create_table(
            "tasks",
            Schema([
                Column("id", DataType.INTEGER),
                Column("status", DataType.VARCHAR, max_length=16),
                Column("assignee", DataType.VARCHAR, nullable=True, max_length=32),
                Column("priority", DataType.VARCHAR, max_length=16),
            ]),
        )
        table.insert([1, "DONE", None, "LOW"])
        table.insert([2, "TODO", "Avery", "LOW"])
        table.insert([3, "DONE", "Blake", "HIGH"])
        table.insert([4, "DONE", "Casey", "LOW"])
        yield engine


def test_lexer_recognizes_delete_case_insensitively_without_matching_prefixes() -> None:
    tokens = Lexer("dElEtE delete_task deletion").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.DELETE,
        TokenType.IDENTIFIER,
        TokenType.IDENTIFIER,
        TokenType.EOF,
    ]
    assert [token.lexeme for token in tokens[:3]] == ["dElEtE", "delete_task", "deletion"]


def test_parser_builds_delete_statement_with_optional_reused_predicate_ast() -> None:
    no_where = _parse("DELETE FROM tasks;")
    assert no_where == DeleteStatement("tasks", None)

    statement = _parse("DELETE FROM tasks WHERE status = 'DONE' AND assignee IS NOT NULL")
    assert isinstance(statement, DeleteStatement)
    assert statement.table_name == "tasks"
    assert statement.where == AndExpression(
        ComparisonExpression("status", "=", "DONE"), IsNullExpression("assignee", True)
    )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE",
        "DELETE tasks",
        "DELETE FROM",
        "DELETE FROM tasks WHERE",
        "DELETE FROM tasks RETURNING id",
        "DELETE FROM tasks LIMIT 1",
    ],
)
def test_parser_rejects_unsupported_delete_syntax(sql: str) -> None:
    with pytest.raises(SQLParseError):
        _parse(sql)


def test_binder_resolves_delete_and_validates_predicate(delete_engine: StrataEngine) -> None:
    bound = Binder(delete_engine.catalog).bind(_parse("DELETE FROM tasks WHERE id = 1"))
    assert isinstance(bound, DeleteCommand)
    assert bound.table is delete_engine.get_table("tasks")
    assert bound.predicate is not None
    assert Binder(delete_engine.catalog).bind(_parse("DELETE FROM tasks")).predicate is None

    with pytest.raises(TableNotFoundError):
        Binder(delete_engine.catalog).bind(_parse("DELETE FROM missing"))
    with pytest.raises(ColumnNotFoundError):
        Binder(delete_engine.catalog).bind(_parse("DELETE FROM tasks WHERE absent = 1"))
    with pytest.raises(TypeMismatchError):
        Binder(delete_engine.catalog).bind(_parse("DELETE FROM tasks WHERE id = 'one'"))


def test_engine_execute_delete_reports_affected_rows_and_preserves_table(delete_engine: StrataEngine) -> None:
    assert delete_engine.execute("DELETE FROM tasks WHERE id = 99") == CommandResult(0)
    assert delete_engine.execute("DELETE FROM tasks WHERE id = 2") == CommandResult(1)
    assert delete_engine.execute("DELETE FROM tasks WHERE status = 'DONE' AND priority = 'LOW'") == CommandResult(2)

    remaining = delete_engine.execute("SELECT id FROM tasks ORDER BY id")
    assert isinstance(remaining, QueryResult)
    assert [row.values for row in remaining.rows] == [(3,)]
    assert delete_engine.has_table("tasks") is True


def test_engine_execute_delete_reuses_null_predicate_semantics(delete_engine: StrataEngine) -> None:
    assert delete_engine.execute("DELETE FROM tasks WHERE assignee IS NULL") == CommandResult(1)
    rows = delete_engine.execute("SELECT id FROM tasks ORDER BY id")
    assert [row.values for row in rows.rows] == [(2,), (3,), (4,)]


def test_delete_without_where_keeps_table_usable_and_allows_later_insert(delete_engine: StrataEngine) -> None:
    assert delete_engine.execute("DELETE FROM tasks") == CommandResult(4)
    assert delete_engine.execute("SELECT * FROM tasks").rows == ()
    assert delete_engine.has_table("tasks") is True

    assert delete_engine.execute("INSERT INTO tasks VALUES (5, 'TODO', NULL, 'HIGH')") == CommandResult(1)
    assert [row.values for row in delete_engine.execute("SELECT id FROM tasks").rows] == [(5,)]


def test_delete_maintains_indexes_and_persists_across_reopen(tmp_path: Path) -> None:
    database = tmp_path / "indexed_database"
    with StrataEngine(database) as engine:
        table = engine.create_table(
            "events",
            Schema([
                Column("id", DataType.INTEGER),
                Column("tag", DataType.VARCHAR, nullable=True, max_length=16),
            ]),
        )
        first = table.insert([1, "remove"])
        remaining = table.insert([2, "keep"])
        engine.create_index("events_tag_idx", "events", "tag")

        assert engine.execute("DELETE FROM events WHERE tag = 'remove'") == CommandResult(1)
        index = table.indexes[0]
        assert index.tree.search("remove") == ()
        assert index.tree.search("keep") == (remaining,)
        assert table.get(remaining)["id"] == 2
        with pytest.raises(RecordNotFoundError):
            table.get(first)

    with StrataEngine(database) as reopened:
        table = reopened.get_table("events")
        assert [row.values for _rid, row in table.scan()] == [(2, "keep")]
        assert table.indexes[0].tree.search("remove") == ()
        assert table.indexes[0].tree.search("keep") == (remaining,)


def test_profiled_delete_is_a_command_without_profile(delete_engine: StrataEngine) -> None:
    result = delete_engine.execute_profiled("DELETE FROM tasks WHERE id = 1")
    assert result.result == CommandResult(1)
    assert result.profile is None
