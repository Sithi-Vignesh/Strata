"""Focused SQL UPDATE frontend, binding, and mutation execution coverage."""

from pathlib import Path

import pytest

from strata_engine import CommandResult, StrataEngine
from strata_engine.catalog import Table
from strata_engine.commands import UpdateCommand
from strata_engine.schema import (
    Column,
    DataType,
    NullConstraintError,
    Schema,
    TupleSerializer,
    TypeMismatchError,
)
from strata_engine.schema.exceptions import ColumnNotFoundError
from strata_engine.sql import Binder, Lexer, Parser, SQLBindingError, SQLLexError, SQLParseError, TokenType
from strata_engine.sql.ast import ComparisonExpression, UpdateStatement


def _parse(sql: str):
    return Parser(Lexer(sql).tokenize()).parse()


@pytest.fixture
def update_engine(tmp_path: Path) -> StrataEngine:
    engine = StrataEngine(tmp_path / "update").open()
    table = engine.create_table(
        "tasks",
        Schema([
            Column("id", DataType.INTEGER),
            Column("status", DataType.VARCHAR, max_length=16),
            Column("priority", DataType.VARCHAR, max_length=16),
            Column("assignee", DataType.VARCHAR, nullable=True, max_length=16),
            Column("active", DataType.BOOLEAN),
        ]),
    )
    table.insert([1, "TODO", "LOW", None, True])
    table.insert([2, "TODO", "HIGH", "Ada", True])
    table.insert([3, "DONE", "LOW", "Bob", False])
    yield engine
    engine.close()


def test_update_lexer_keywords_are_case_insensitive_and_keep_boundaries() -> None:
    tokens = Lexer("uPdAtE updates SET setting = TRUE").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.UPDATE,
        TokenType.IDENTIFIER,
        TokenType.SET,
        TokenType.IDENTIFIER,
        TokenType.EQUAL,
        TokenType.TRUE,
        TokenType.EOF,
    ]
    assert [token.lexeme for token in tokens[1:4:2]] == ["updates", "setting"]


def test_update_parser_preserves_ordered_literal_assignments_and_where() -> None:
    statement = _parse("UPDATE tasks SET status = 'DONE', priority = 'HIGH' WHERE id = 1;")
    assert isinstance(statement, UpdateStatement)
    assert statement.table_name == "tasks"
    assert [(item.column_name, item.value) for item in statement.assignments] == [
        ("status", "DONE"),
        ("priority", "HIGH"),
    ]
    assert statement.where == ComparisonExpression("id", "=", 1)
    assert _parse("UPDATE tasks SET assignee = NULL").where is None
    literals = _parse("UPDATE tasks SET whole = 12, decimal = 1.5, text = 'x', flag = TRUE, empty = NULL")
    assert [item.value for item in literals.assignments] == [12, 1.5, "x", True, None]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE;",
        "UPDATE tasks;",
        "UPDATE tasks SET;",
        "UPDATE tasks SET status;",
        "UPDATE tasks SET status =;",
        "UPDATE tasks SET status = other_column;",
        "UPDATE tasks SET status = 'DONE',;",
        "UPDATE tasks SET id = id + 1;",
        "UPDATE tasks SET status = 'DONE' RETURNING id;",
    ],
)
def test_update_parser_rejects_malformed_or_unsupported_forms(sql: str) -> None:
    with pytest.raises((SQLParseError, SQLLexError)):
        _parse(sql)


def test_update_binder_resolves_ordinals_and_rejects_invalid_assignments(update_engine: StrataEngine) -> None:
    bound = Binder(update_engine.catalog).bind(
        _parse("UPDATE tasks SET status = 'DONE', active = FALSE WHERE id = 1")
    )
    assert isinstance(bound, UpdateCommand)
    assert [(item.column_index, item.value) for item in bound.assignments] == [(1, "DONE"), (4, False)]
    assert bound.predicate is not None

    for sql, error in [
        ("UPDATE tasks SET missing = 1", ColumnNotFoundError),
        ("UPDATE tasks SET status = 'A', STATUS = 'B'", SQLBindingError),
        ("UPDATE tasks SET id = 'hello'", TypeMismatchError),
        ("UPDATE tasks SET id = NULL", NullConstraintError),
        ("UPDATE tasks SET active = 42", TypeMismatchError),
    ]:
        with pytest.raises(error):
            Binder(update_engine.catalog).bind(_parse(sql))


def test_sql_update_commands_cover_matching_multiple_literals_and_indexes(update_engine: StrataEngine) -> None:
    table = update_engine.get_table("tasks")
    rids = {row["id"]: rid for rid, row in table.scan()}
    update_engine.create_index("tasks_status_idx", "tasks", "status")
    index = table.indexes[0]

    assert update_engine.execute("UPDATE tasks SET status = 'READY' WHERE id = 999") == CommandResult(0)
    assert update_engine.execute("UPDATE tasks SET status = 'READY', priority = 'URGENT' WHERE id = 1") == CommandResult(1)
    assert table.get(index.tree.search("READY")[0]).values == (1, "READY", "URGENT", None, True)
    assert index.tree.search("TODO") == (rids[2],)

    assert update_engine.execute("UPDATE tasks SET assignee = NULL WHERE id = 2") == CommandResult(1)
    assert update_engine.execute(
        "UPDATE tasks SET active = FALSE WHERE (id = 1 OR id = 2) AND NOT active = FALSE"
    ) == CommandResult(2)
    assert update_engine.execute("UPDATE tasks SET priority = 'MEDIUM'") == CommandResult(3)
    rows = {row["id"]: row.values for _, row in table.scan()}
    assert rows == {
        1: (1, "READY", "MEDIUM", None, False),
        2: (2, "TODO", "MEDIUM", None, False),
        3: (3, "DONE", "MEDIUM", "Bob", False),
    }
    assert index.tree.search("TODO") == (next(rid for rid, row in table.scan() if row["id"] == 2),)
    assert index.tree.search("READY") == (next(rid for rid, row in table.scan() if row["id"] == 1),)


def test_sql_update_prepares_all_replacements_before_first_table_update(update_engine: StrataEngine, monkeypatch) -> None:
    table = update_engine.get_table("tasks")
    events: list[str] = []
    original_serialize = TupleSerializer.serialize

    def record_full_row_validation(self, row):
        if self.schema.fingerprint == table.schema.fingerprint:
            events.append("validate")
        return original_serialize(self, row)

    def record_update(self, record_id, row):
        events.append("update")
        return record_id

    monkeypatch.setattr(TupleSerializer, "serialize", record_full_row_validation)
    monkeypatch.setattr(Table, "update", record_update)
    assert update_engine.execute("UPDATE tasks SET status = 'READY'") == CommandResult(3)
    assert events == ["validate", "validate", "validate", "update", "update", "update"]


def test_sql_update_relocation_uses_table_update_and_moves_index(tmp_path: Path) -> None:
    with StrataEngine(tmp_path / "relocation") as engine:
        table = engine.create_table(
            "items",
            Schema([
                Column("id", DataType.INTEGER),
                Column("payload", DataType.VARCHAR, max_length=3000),
            ]),
        )
        old_rid = table.insert([7, "A" * 1000])
        table.insert([8, "B" * 2500])
        engine.create_index("items_id_idx", "items", "id")
        index = table.indexes[0]

        assert engine.execute(f"UPDATE items SET payload = '{'C' * 1600}' WHERE id = 7") == CommandResult(1)
        new_rid = index.tree.search(7)[0]
        assert new_rid != old_rid
        assert table.get(new_rid).values == (7, "C" * 1600)


def test_sql_update_multi_row_snapshot_processes_original_targets_once(tmp_path: Path, monkeypatch) -> None:
    with StrataEngine(tmp_path / "snapshot") as engine:
        table = engine.create_table(
            "items",
            Schema([
                Column("id", DataType.INTEGER),
                Column("payload", DataType.VARCHAR, max_length=3000),
            ]),
        )
        first = table.insert([7, "A" * 1000])
        second = table.insert([8, "B" * 2500])
        calls = []
        original_update = Table.update

        def record_update(self, record_id, row):
            calls.append(record_id)
            return original_update(self, record_id, row)

        monkeypatch.setattr(Table, "update", record_update)
        assert engine.execute(f"UPDATE items SET payload = '{'C' * 1600}'") == CommandResult(2)
        assert calls == [first, second]
        assert sorted(row.values for _, row in table.scan()) == [(7, "C" * 1600), (8, "C" * 1600)]


def test_profiled_update_is_a_command_without_profile(update_engine: StrataEngine) -> None:
    result = update_engine.execute_profiled("UPDATE tasks SET active = FALSE WHERE id = 1")
    assert result.result == CommandResult(1)
    assert result.profile is None


def test_sql_update_persists_indexed_column_changes_across_reopen(tmp_path: Path) -> None:
    database = tmp_path / "persistence"
    with StrataEngine(database) as engine:
        table = engine.create_table(
            "items",
            Schema([
                Column("id", DataType.INTEGER),
                Column("tag", DataType.VARCHAR, max_length=16),
            ]),
        )
        table.insert([1, "old"])
        engine.create_index("items_tag_idx", "items", "tag")
        assert engine.execute("UPDATE items SET tag = 'new' WHERE id = 1") == CommandResult(1)

    with StrataEngine(database) as reopened:
        table = reopened.get_table("items")
        rid, row = next(table.scan())
        assert row.values == (1, "new")
        assert table.indexes[0].tree.search("old") == ()
        assert table.indexes[0].tree.search("new") == (rid,)
