"""Persistent B+ tree storage tests for Phase 19."""

from pathlib import Path
import random

import pytest

from strata_engine.schema import DataType
from strata_engine.storage import (
    BPlusTree,
    BPlusTreeCorruptionError,
    InvalidKeyError,
    KeyTooLargeError,
    KeyTypeMismatchError,
    RecordId,
    UnsupportedKeyTypeError,
)


def test_create_empty_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "numbers.bpt"
    with BPlusTree.create(path, DataType.INTEGER, pool_size=1) as tree:
        assert tree.height == 1
        assert tree.entry_count == 0
        assert tree.search(2) == ()
        assert tree.scan_range() == ()
        assert tree.last_operation_stats.tree_pages_visited == 1
    with BPlusTree.open(path, DataType.INTEGER, pool_size=1) as reopened:
        assert reopened.height == 1
        assert reopened.entry_count == 0
        reopened.validate_structure()


@pytest.mark.parametrize(
    ("key_type", "keys"),
    [
        (DataType.INTEGER, [3, -1, 2]),
        (DataType.BIGINT, [2**40, -(2**40), 0]),
        (DataType.BOOLEAN, [True, False]),
        (DataType.VARCHAR, ["zebra", "alpha", "éclair"]),
    ],
)
def test_supported_key_types_are_ordered(tmp_path: Path, key_type: DataType, keys: list[object]) -> None:
    path = tmp_path / f"{key_type.value}.bpt"
    with BPlusTree.create(path, key_type) as tree:
        for slot, key in enumerate(keys):
            assert tree.insert(key, RecordId(1, slot))
        assert [key for key, _ in tree.scan_range()] == sorted(keys)
        assert tree.search(keys[0]) == (RecordId(1, 0),)
        tree.validate_structure()


def test_strict_keys_duplicate_pairs_and_ranges(tmp_path: Path) -> None:
    path = tmp_path / "duplicates.bpt"
    with BPlusTree.create(path, DataType.INTEGER, pool_size=2) as tree:
        pairs = [(5, RecordId(2, 8)), (2, RecordId(1, 1)), (5, RecordId(1, 9)), (8, RecordId(3, 0))]
        for key, rid in pairs:
            assert tree.insert(key, rid)
        assert not tree.insert(5, RecordId(1, 9))
        assert tree.search(5) == (RecordId(1, 9), RecordId(2, 8))
        assert tree.scan_range(2, 8, lower_inclusive=False, upper_inclusive=False) == ((5, RecordId(1, 9)), (5, RecordId(2, 8)))
        assert [key for key, _ in tree.scan_range(5)] == [5, 5, 8]
        with pytest.raises(InvalidKeyError):
            tree.insert(True, RecordId(0, 0))
        with pytest.raises(InvalidKeyError):
            tree.search(None)
        tree.validate_structure()


def test_leaf_splits_duplicate_keys_persistence_and_small_pool(tmp_path: Path) -> None:
    path = tmp_path / "split.bpt"
    expected = tuple(RecordId(page, 0) for page in range(260))
    with BPlusTree.create(path, DataType.INTEGER, pool_size=1) as tree:
        for rid in reversed(expected):
            assert tree.insert(7, rid)
        assert tree.leaf_page_count > 1
        assert tree.search(7) == expected
        assert tree.last_operation_stats.tree_pages_visited > 1
        assert tree.last_operation_stats.leaf_entries_examined >= len(expected)
        assert tree.scan_range(7, 7) == tuple((7, rid) for rid in expected)
        tree.validate_structure()
    with BPlusTree.open(path, DataType.INTEGER, pool_size=1) as tree:
        assert tree.search(7) == expected
        tree.validate_structure()


def test_variable_varchar_splits_and_bounds(tmp_path: Path) -> None:
    path = tmp_path / "text.bpt"
    with BPlusTree.create(path, DataType.VARCHAR, pool_size=2) as tree:
        keys = ["a" * 1100 + str(i) for i in range(6)]
        for index, key in enumerate(reversed(keys)):
            tree.insert(key, RecordId(index + 1, 0))
        assert tree.leaf_page_count > 1
        assert [key for key, _ in tree.scan_range()] == sorted(keys)
        with pytest.raises(KeyTooLargeError):
            tree.insert("x" * (tree.max_key_bytes + 1), RecordId(99, 0))
        tree.validate_structure()


def test_internal_split_and_multilevel_reopen(tmp_path: Path) -> None:
    """Real page capacities force an internal-root split without a test hook."""
    path = tmp_path / "multilevel.bpt"
    count = 14_000
    with BPlusTree.create(path, DataType.INTEGER, pool_size=2) as tree:
        for key in range(count):
            tree.insert(key, RecordId(key + 1, 0))
        assert tree.height >= 3
        assert tree.search(0) == (RecordId(1, 0),)
        assert tree.search(count - 1) == (RecordId(count, 0),)
        tree.validate_structure()
    with BPlusTree.open(path, DataType.INTEGER, pool_size=2) as tree:
        assert tree.height >= 3
        assert tree.entry_count == count
        assert tree.scan_range(count - 2) == (
            (count - 2, RecordId(count - 1, 0)),
            (count - 1, RecordId(count, 0)),
        )
        tree.validate_structure()


def test_randomized_reference_and_metrics(tmp_path: Path) -> None:
    path = tmp_path / "random.bpt"
    rng = random.Random(19019)
    pairs = [(rng.randrange(-100, 101), RecordId(index + 1, rng.randrange(4))) for index in range(800)]
    expected = sorted(set(pairs), key=lambda pair: (pair[0], int(pair[1].page_id), pair[1].slot_id))
    rng.shuffle(pairs)
    with BPlusTree.create(path, DataType.INTEGER, pool_size=2) as tree:
        for key, rid in pairs:
            tree.insert(key, rid)
        assert tree.scan_range(-20, 20) == tuple(pair for pair in expected if -20 <= pair[0] <= 20)
        assert tree.last_operation_stats.tree_pages_visited > 1
        assert tree.last_operation_stats.leaf_entries_examined > 0
        for key in (-100, -3, 0, 99):
            assert tree.search(key) == tuple(rid for stored_key, rid in expected if stored_key == key)
        tree.validate_structure()


def test_type_open_and_header_validation(tmp_path: Path) -> None:
    path = tmp_path / "format.bpt"
    with pytest.raises(UnsupportedKeyTypeError):
        BPlusTree.create(path, DataType.FLOAT)
    with BPlusTree.create(path, DataType.INTEGER):
        pass
    with pytest.raises(KeyTypeMismatchError):
        BPlusTree.open(path, DataType.BIGINT)
    raw = bytearray(path.read_bytes())
    raw[:8] = b"BROKEN!!"
    path.write_bytes(raw)
    with pytest.raises(BPlusTreeCorruptionError):
        BPlusTree.open(path)
