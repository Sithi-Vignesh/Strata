"""Focused Phase 20 persistent-index lifecycle coverage."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog, CatalogCorruptionError
from strata_engine.schema import Column, DataType, Schema


def _schema() -> Schema:
    return Schema([
        Column("id", DataType.INTEGER, nullable=False),
        Column("tag", DataType.VARCHAR, nullable=True, max_length=32),
    ])


def test_backfill_insert_delete_reopen_and_drop(tmp_path: Path) -> None:
    database = tmp_path / "indexed"
    with Catalog(database, default_pool_size=2) as catalog:
        table = catalog.create_table("events", _schema())
        first = table.insert([1, "same"])
        null_row = table.insert([2, None])
        catalog.create_index("event_tag", "events", "tag")
        binding = table.indexes[0]
        assert binding.tree.search("same") == (first,)
        assert binding.tree.search("") == ()
        later = table.insert([3, "same"])
        assert binding.tree.search("same") == (first, later)
        table.delete(first)
        assert binding.tree.search("same") == (later,)
        table.delete(null_row)
    with Catalog(database, default_pool_size=2) as catalog:
        table = catalog.get_table("events")
        assert table.indexes[0].tree.search("same") == (later,)
        catalog.drop_table("events")
        assert not (database / "indexes" / "index_1.db").exists()
    with Catalog(database) as catalog:
        assert catalog.list_tables() == []


def test_legacy_catalog_bootstraps_empty_index_catalog(tmp_path: Path) -> None:
    database = tmp_path / "legacy"
    with Catalog(database) as catalog:
        catalog.create_table("events", _schema())
    (database / "catalog" / "indexes.db").unlink()
    with Catalog(database) as catalog:
        assert catalog.get_table("events").indexes == ()
        assert (database / "catalog" / "indexes.db").exists()


def test_missing_index_catalog_with_persisted_index_file_is_corruption(tmp_path: Path) -> None:
    database = tmp_path / "partial-index-catalog"
    with Catalog(database) as catalog:
        catalog.create_table("events", _schema())
        catalog.create_index("event_tag", "events", "tag")
    (database / "catalog" / "indexes.db").unlink()

    with pytest.raises(CatalogCorruptionError, match="Persisted index files exist"):
        Catalog(database)
