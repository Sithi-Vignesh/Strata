"""Focused relational update coverage for the Table API."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog
from strata_engine.schema import (
    Column,
    DataType,
    NullConstraintError,
    Schema,
    SchemaMismatchError,
    Tuple,
    TypeMismatchError,
    ValueOutOfRangeError,
)
from strata_engine.storage import RecordNotFoundError
from strata_engine.storage.b_plus_tree import BPlusTree


def _table(catalog: Catalog, name: str = "items"):
    return catalog.create_table(
        name,
        Schema([
            Column("id", DataType.INTEGER),
            Column("tag", DataType.VARCHAR, nullable=True, max_length=32),
            Column("payload", DataType.VARCHAR, max_length=3000),
        ]),
    )


def test_update_same_page_preserves_rid_and_persists(tmp_path: Path) -> None:
    database = tmp_path / "same_page"
    with Catalog(database) as catalog:
        table = _table(catalog)
        rid = table.insert([1, "old", "A" * 100])

        assert table.update(rid, Tuple([1, "new", "B" * 50], schema=table.schema)) == rid
        assert table.get(rid).values == (1, "new", "B" * 50)
        assert list(table.scan()) == [(rid, table.get(rid))]

    with Catalog(database) as catalog:
        table = catalog.get_table("items")
        assert table.get(rid).values == (1, "new", "B" * 50)


def test_update_same_page_maintains_changed_null_and_multiple_indexes(tmp_path: Path) -> None:
    with Catalog(tmp_path / "indexes") as catalog:
        table = _table(catalog)
        rid = table.insert([1, None, "small"])
        catalog.create_index("items_id_idx", "items", "id")
        catalog.create_index("items_tag_idx", "items", "tag")
        id_index, tag_index = table.indexes

        assert table.update(rid, Tuple([2, "active", "small"], schema=table.schema)) == rid
        assert id_index.tree.search(1) == ()
        assert id_index.tree.search(2) == (rid,)
        assert tag_index.tree.search("active") == (rid,)

        assert table.update(rid, Tuple([3, None, "small"], schema=table.schema)) == rid
        assert id_index.tree.search(2) == ()
        assert id_index.tree.search(3) == (rid,)
        assert tag_index.tree.search("active") == ()
        assert table.get(rid).values == (3, None, "small")


def test_update_relocation_moves_unchanged_index_key_to_new_rid(tmp_path: Path) -> None:
    with Catalog(tmp_path / "relocation") as catalog:
        table = _table(catalog)
        old_rid = table.insert([7, "stable", "A" * 1000])
        blocker = table.insert([8, "other", "B" * 2500])
        assert blocker.page_id == old_rid.page_id
        catalog.create_index("items_id_idx", "items", "id")
        index = table.indexes[0]
        assert index.tree.search(7) == (old_rid,)

        new_rid = table.update(old_rid, Tuple([7, "stable", "C" * 1600], schema=table.schema))

        assert new_rid != old_rid
        assert new_rid.page_id != old_rid.page_id
        with pytest.raises(RecordNotFoundError):
            table.get(old_rid)
        assert table.get(new_rid).values == (7, "stable", "C" * 1600)
        assert index.tree.search(7) == (new_rid,)
        assert [rid for rid, row in table.scan() if row["id"] == 7] == [new_rid]


@pytest.mark.parametrize(
    "row,error",
    [
        (Tuple(["bad", "tag", "payload"]), TypeMismatchError),
        (Tuple([1, "tag", None]), NullConstraintError),
        (Tuple([1, "tag", "X" * 3001]), ValueOutOfRangeError),
    ],
)
def test_update_validation_failure_leaves_old_row_and_indexes_unchanged(tmp_path: Path, row: Tuple, error: type[Exception]) -> None:
    with Catalog(tmp_path / "validation") as catalog:
        table = _table(catalog)
        rid = table.insert([1, "old", "payload"])
        catalog.create_index("items_tag_idx", "items", "tag")
        index = table.indexes[0]

        with pytest.raises(error):
            table.update(rid, row)

        assert table.get(rid).values == (1, "old", "payload")
        assert index.tree.search("old") == (rid,)


def test_update_rejects_wrong_schema_and_deleted_rid_without_mutation(tmp_path: Path) -> None:
    with Catalog(tmp_path / "invalid") as catalog:
        table = _table(catalog)
        rid = table.insert([1, "old", "payload"])
        wrong_schema = Schema([Column("only", DataType.INTEGER)])
        with pytest.raises(SchemaMismatchError):
            table.update(rid, Tuple([1], schema=wrong_schema))
        assert table.get(rid).values == (1, "old", "payload")

        table.delete(rid)
        with pytest.raises(RecordNotFoundError):
            table.update(rid, Tuple([1, "new", "payload"], schema=table.schema))


def test_update_same_page_index_failure_restores_heap_and_index(tmp_path: Path, monkeypatch) -> None:
    with Catalog(tmp_path / "compensation") as catalog:
        table = _table(catalog)
        rid = table.insert([1, "old", "payload"])
        catalog.create_index("items_tag_idx", "items", "tag")
        index = table.indexes[0]
        original_insert = BPlusTree.insert

        def fail_new_key(self, key, record_id):
            if self is index.tree and key == "new":
                raise RuntimeError("simulated index insert failure")
            return original_insert(self, key, record_id)

        monkeypatch.setattr(BPlusTree, "insert", fail_new_key)
        with pytest.raises(RuntimeError, match="simulated index insert failure"):
            table.update(rid, Tuple([1, "new", "payload"], schema=table.schema))

        assert table.get(rid).values == (1, "old", "payload")
        assert index.tree.search("old") == (rid,)
        assert index.tree.search("new") == ()


def test_update_relocation_index_failure_removes_temporary_row(tmp_path: Path, monkeypatch) -> None:
    with Catalog(tmp_path / "relocation_compensation") as catalog:
        table = _table(catalog)
        old_rid = table.insert([7, "old", "A" * 1000])
        table.insert([8, "blocker", "B" * 2500])
        catalog.create_index("items_tag_idx", "items", "tag")
        index = table.indexes[0]
        old_tuple = table.get(old_rid)
        original_insert = BPlusTree.insert

        def fail_replacement_key(self, key, record_id):
            if self is index.tree and key == "new":
                raise RuntimeError("simulated relocation index insert failure")
            return original_insert(self, key, record_id)

        monkeypatch.setattr(BPlusTree, "insert", fail_replacement_key)
        with pytest.raises(RuntimeError, match="simulated relocation index insert failure"):
            table.update(old_rid, Tuple([7, "new", "C" * 1600], schema=table.schema))

        assert table.get(old_rid) == old_tuple
        assert [rid for rid, row in table.scan() if row["id"] == 7] == [old_rid]
        assert [row for _, row in table.scan() if row["tag"] == "new"] == []
        assert index.tree.search("old") == (old_rid,)
        assert index.tree.search("new") == ()
        assert len(list(table.scan())) == 2
        assert table.insert([9, "usable", "payload"])


def test_update_relocation_partial_multi_index_failure_restores_indexes(tmp_path: Path, monkeypatch) -> None:
    with Catalog(tmp_path / "partial_relocation_compensation") as catalog:
        table = _table(catalog)
        old_rid = table.insert([7, "old", "A" * 1000])
        table.insert([8, "blocker", "B" * 2500])
        catalog.create_index("items_id_idx", "items", "id")
        catalog.create_index("items_tag_idx", "items", "tag")
        id_index, tag_index = table.indexes
        original_insert = BPlusTree.insert

        def fail_second_index(self, key, record_id):
            if self is tag_index.tree and key == "new":
                raise RuntimeError("simulated second index insert failure")
            return original_insert(self, key, record_id)

        monkeypatch.setattr(BPlusTree, "insert", fail_second_index)
        with pytest.raises(RuntimeError, match="simulated second index insert failure"):
            table.update(old_rid, Tuple([9, "new", "C" * 1600], schema=table.schema))

        assert table.get(old_rid).values == (7, "old", "A" * 1000)
        assert [rid for rid, row in table.scan() if row["id"] == 7] == [old_rid]
        assert [row for _, row in table.scan() if row["id"] == 9] == []
        assert id_index.tree.search(7) == (old_rid,)
        assert id_index.tree.search(9) == ()
        assert tag_index.tree.search("old") == (old_rid,)
        assert tag_index.tree.search("new") == ()
        assert len(list(table.scan())) == 2
