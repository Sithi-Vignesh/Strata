"""Deterministic storage integrity, failure compensation and eviction regressions."""
import random

import pytest

from strata_engine.catalog import Catalog
from strata_engine.schema import Column, DataType, Schema, Tuple
from strata_engine.storage import BPlusTree, RecordId


def assert_indexes_match_scan(table):
    rows = list(table.scan())
    for index in table.indexes:
        expected = {(row[index.column_ordinal], rid) for rid, row in rows if row[index.column_ordinal] is not None}
        actual = index.tree.scan_range()
        assert set(actual) == expected
        assert len(actual) == len(expected) == index.tree.entry_count
        for key in {key for key, _ in expected}:
            assert set(index.tree.search(key)) == {rid for candidate, rid in expected if candidate == key}
        index.tree.validate_structure()
        assert all(frame.pin_count == 0 for frame in index.tree._buffer_pool._frames)
    assert all(frame.pin_count == 0 for frame in table.heap_file.buffer_pool_manager._frames)


def test_variable_length_deletion_keeps_index_and_heap_consistent_after_reopen(tmp_path):
    rng = random.Random(7031)
    keys = [(i, f"{i:04d}" + "x" * rng.choice([0, 8, 100, 500, 1000, 1800])) for i in range(180)]
    rng.shuffle(keys)
    directory = tmp_path / "deletions"
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.create_table("items", Schema([
            Column("id", DataType.INTEGER),
            Column("tag", DataType.VARCHAR, max_length=2000),
        ]))
        catalog.create_index("tag_index", "items", "tag")
        for logical_id, key in keys:
            table.insert([logical_id, key])
        assert table.indexes[0].tree.height >= 3
        assert_indexes_match_scan(table)
    rng.shuffle(keys)
    # Delete through Table so every rejected/partial index operation would be
    # observable as a mismatch with the authoritative heap, including reopen.
    for batch in range(3):
        with Catalog(directory, default_pool_size=1) as catalog:
            table = catalog.get_table("items")
            by_id = {row[0]: rid for rid, row in table.scan()}
            for position, (logical_id, key) in enumerate(keys[batch * 60:(batch + 1) * 60]):
                table.delete(by_id[logical_id])
                assert table.indexes[0].tree.search(key) == ()
                table.indexes[0].tree.validate_structure()
                if position % 15 == 0:
                    assert_indexes_match_scan(table)
            assert_indexes_match_scan(table)
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert table.count() == 0
        # Reuse deleted heap slots and the normalized empty index root.
        for logical_id, key in keys[:20]:
            table.insert([logical_id, key])
        assert_indexes_match_scan(table)
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert table.count() == 20
        assert_indexes_match_scan(table)


@pytest.mark.parametrize("size", [3000, 4054])
def test_legal_large_middle_key_can_require_three_leaf_pages(tmp_path, size):
    path = tmp_path / "large_keys.db"
    expected = (('a' * 1500, RecordId(1, 0)), ('b' * size, RecordId(2, 0)), ('c' * 1500, RecordId(3, 0)))
    with BPlusTree.create(path, DataType.VARCHAR, pool_size=1) as tree:
        for key, rid in (expected[0], expected[2], expected[1]):
            assert tree.insert(key, rid)
        assert tree.leaf_page_count == 3
        assert tree.scan_range() == expected
        for key, rid in expected:
            assert tree.search(key) == (rid,)
            assert not tree.insert(key, rid)
        tree.validate_structure()
    with BPlusTree.open(path, pool_size=1) as tree:
        assert tree.scan_range() == expected
        tree.validate_structure()
        for key, rid in expected:
            assert tree.delete(key, rid)
            tree.validate_structure()
        assert tree.scan_range() == ()


def test_seeded_mutations_duplicate_null_keys_relocation_and_reopen(tmp_path):
    directory = tmp_path / "mutations"
    rng = random.Random(19173)
    expected = {}
    next_id = 0
    for batch in range(3):
        with Catalog(directory, default_pool_size=1) as catalog:
            if batch == 0:
                table = catalog.create_table("items", Schema([
                    Column("id", DataType.INTEGER),
                    Column("tag", DataType.VARCHAR, nullable=True, max_length=40),
                    Column("payload", DataType.VARCHAR, max_length=2800),
                ]))
                catalog.create_index("id_index", "items", "id")
                catalog.create_index("tag_index", "items", "tag")
            else:
                table = catalog.get_table("items")
            for _ in range(65):
                by_id = {row[0]: rid for rid, row in table.scan()}
                operation = rng.choice(["insert", "insert", "update", "delete"])
                if not by_id or operation == "insert":
                    row = (next_id, rng.choice([None, "same", "", "தமிழ்"]), "x" * rng.choice([0, 20, 1000, 2500]))
                    table.insert(row)
                    expected[next_id] = row
                    next_id += 1
                else:
                    logical_id = rng.choice(sorted(by_id))
                    if operation == "delete":
                        table.delete(by_id[logical_id])
                        del expected[logical_id]
                    else:
                        row = (logical_id, rng.choice([None, "same", "", "éclair"]), "y" * rng.choice([0, 20, 1000, 2500]))
                        table.update(by_id[logical_id], Tuple(row, table.schema))
                        expected[logical_id] = row
                assert {row[0]: row.values for _, row in table.scan()} == expected
                assert_indexes_match_scan(table)
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert {row[0]: row.values for _, row in table.scan()} == expected
        assert_indexes_match_scan(table)


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_second_index_failure_compensates_and_persists(tmp_path, monkeypatch, operation):
    directory = tmp_path / "compensation"
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.create_table("items", Schema([
            Column("id", DataType.INTEGER),
            Column("tag", DataType.VARCHAR, max_length=30),
        ]))
        catalog.create_index("id_index", "items", "id")
        catalog.create_index("tag_index", "items", "tag")
        rid = table.insert([1, "old"])
        before = list(table.scan())
        target = table.indexes[1].tree
        method = "delete" if operation == "delete" else "insert"
        original = getattr(BPlusTree, method)
        failed = False

        def fail_once(self, key, record_id):
            nonlocal failed
            if self is target and not failed:
                failed = True
                raise OSError("controlled index maintenance failure")
            return original(self, key, record_id)

        with monkeypatch.context() as patch:
            patch.setattr(BPlusTree, method, fail_once)
            with pytest.raises(OSError, match="controlled index maintenance failure"):
                if operation == "insert":
                    table.insert([2, "new"])
                elif operation == "update":
                    table.update(rid, Tuple([2, "new"], table.schema))
                else:
                    table.delete(rid)
        assert failed
        assert list(table.scan()) == before
        assert_indexes_match_scan(table)
        # A subsequent successful operation proves exception/lock cleanup.
        table.insert([3, "after"])
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert {row.values for _, row in table.scan()} == {(1, "old"), (3, "after")}
        assert_indexes_match_scan(table)


def test_root_allocation_failure_after_split_restores_index_and_reopens(tmp_path, monkeypatch):
    from strata_engine.storage.b_plus_tree import INTERNAL

    directory = tmp_path / "split_failure"
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.create_table("items", Schema([Column("id", DataType.INTEGER)]))
        catalog.create_index("by_id", "items", "id")
        for logical_id in range(185):
            table.insert([logical_id])
        tree = table.indexes[0].tree
        allocate = BPlusTree._allocate_node
        failed = False

        def fail_root(self, node):
            nonlocal failed
            if self is tree and node.node_type == INTERNAL and not failed:
                failed = True
                raise OSError("controlled root allocation failure")
            return allocate(self, node)

        with monkeypatch.context() as patch:
            patch.setattr(BPlusTree, "_allocate_node", fail_root)
            with pytest.raises(OSError, match="controlled root allocation failure"):
                table.insert([185])
        assert failed
        assert table.count() == 185
        assert tree.search(185) == ()
        assert_indexes_match_scan(table)
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert table.count() == 185
        assert_indexes_match_scan(table)
        table.insert([185])
        assert_indexes_match_scan(table)
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert table.count() == 186
        assert_indexes_match_scan(table)


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_exception_after_node_write_restores_row_and_index(tmp_path, monkeypatch, operation):
    directory = tmp_path / "node_failure"
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.create_table("items", Schema([Column("id", DataType.INTEGER)]))
        catalog.create_index("by_id", "items", "id")
        rid = table.insert([1])
        tree = table.indexes[0].tree
        original = BPlusTree._write_node
        failed = False

        def fail_after_write(self, pid, node):
            nonlocal failed
            original(self, pid, node)
            if self is tree and not failed:
                failed = True
                raise OSError("controlled failure after node write")

        with monkeypatch.context() as patch:
            patch.setattr(BPlusTree, "_write_node", fail_after_write)
            with pytest.raises(OSError, match="controlled failure after node write"):
                if operation == "insert":
                    table.insert([2])
                elif operation == "update":
                    table.update(rid, Tuple([2], table.schema))
                else:
                    table.delete(rid)
        assert failed
        assert [row.values for _, row in table.scan()] == [(1,)]
        assert_indexes_match_scan(table)
    with Catalog(directory, default_pool_size=1) as catalog:
        table = catalog.get_table("items")
        assert [row.values for _, row in table.scan()] == [(1,)]
        assert_indexes_match_scan(table)


def test_retained_bounds_route_interleaved_variable_keys_and_duplicate_rids(tmp_path):
    rng = random.Random(7031)
    initial = [(f"{i:04d}" + "x" * rng.choice([0, 8, 100, 500, 1000, 1800]), RecordId(i, 0)) for i in range(180)]
    rng.shuffle(initial)
    expected = set(initial)
    path = tmp_path / "retained_bounds.db"

    def order(pair):
        return pair[0], int(pair[1].page_id), pair[1].slot_id

    def verify(tree):
        assert tree.scan_range() == tuple(sorted(expected, key=order))
        assert tree.entry_count == len(expected)
        for key in {key for key, _ in expected}:
            assert tree.search(key) == tuple(rid for candidate, rid in sorted(expected, key=order) if candidate == key)
        bounds = sorted({key for key, _ in expected})
        for lower, upper in zip(bounds[::13], bounds[9::13]):
            assert tree.scan_range(lower, upper, lower_inclusive=False) == tuple(
                pair for pair in sorted(expected, key=order) if lower < pair[0] <= upper
            )
        tree.validate_structure()

    def has_retained_bound(tree, pid):
        node = tree._read_node(pid)
        if node.children is None:
            return False
        for separator, child in zip(node.entries, node.children[1:]):
            minimum = tree._read_node(child)
            while minimum.children is not None:
                minimum = tree._read_node(minimum.children[0])
            if tree._pair(separator) < tree._pair(minimum.entries[0]):
                return True
        return any(has_retained_bound(tree, child) for child in node.children)

    with BPlusTree.create(path, DataType.VARCHAR, pool_size=1) as tree:
        for key, rid in initial:
            tree.insert(key, rid)
        rng.shuffle(initial)
        for key, rid in initial[:60]:
            assert tree.delete(key, rid)
            expected.remove((key, rid))
        assert has_retained_bound(tree, int(tree.root_page_id))
        verify(tree)
    # Keep the tree populated while inserting back into retained boundary
    # gaps, duplicating large keys across leaves, and causing further splits.
    for batch in range(3):
        with BPlusTree.open(path, pool_size=1) as tree:
            allocated = tree.tree_page_count
            for position, (key, old_rid) in enumerate(initial[batch * 20:(batch + 1) * 20]):
                additions = [
                    (key, RecordId(int(old_rid.page_id), 1)),
                    (key, RecordId(1000 + batch * 20 + position, 0)),
                    (key + "z", RecordId(2000 + batch * 20 + position, 0)),
                ]
                for new_key, rid in additions:
                    assert tree.insert(new_key, rid)
                    expected.add((new_key, rid))
                if position % 4 == 0:
                    candidate = initial[60 + batch * 20 + position]
                    assert tree.delete(*candidate)
                    expected.remove(candidate)
                    verify(tree)
            assert tree.tree_page_count > allocated
            verify(tree)
    with BPlusTree.open(path, pool_size=1) as tree:
        verify(tree)
