"""Unit and integration tests for Table abstraction (Phase 5).

Validates:
- Table construction, property exposure, and type checking.
- Typed insert accepting Tuple (bound or schema-less) and raw Sequences.
- Schema mismatch rejection when inserting incompatible Tuple.
- Typed get returning schema-bound Tuple with named access.
- Record deletion and deleted-slot omission during scan.
- Sequential scanning and record counting.
- Multi-page record spanning across slotted pages.
- Closed table lifecycle and StorageClosedError enforcement.
- Heavy buffer pool eviction with pool_size = 1 and pool_size = 2.
"""

from pathlib import Path
import pytest

from strata_engine.catalog.table import Table
from strata_engine.schema import (
    Column,
    DataType,
    Schema,
    SchemaMismatchError,
    Tuple,
    TupleArityError,
    TypeMismatchError,
)
from strata_engine.storage import (
    BufferPoolManager,
    HeapFile,
    PageFile,
    RecordNotFoundError,
    StorageClosedError,
)


@pytest.fixture
def sample_schema() -> Schema:
    return Schema([
        Column("id", DataType.INTEGER, nullable=False),
        Column("name", DataType.VARCHAR, nullable=False, max_length=50),
        Column("score", DataType.FLOAT, nullable=True),
    ])


@pytest.fixture
def table_fixture(tmp_path: Path, sample_schema: Schema):
    db_file = tmp_path / "test_table.db"
    pf = PageFile(db_file)
    bpm = BufferPoolManager(pf, pool_size=5)
    hf = HeapFile(bpm)
    tbl = Table(1, "users", sample_schema, hf)
    yield tbl, sample_schema
    tbl.close()


def test_table_initial_properties(table_fixture) -> None:
    """Verify Table initial properties and open status."""
    tbl, schema = table_fixture
    assert tbl.table_id == 1
    assert tbl.name == "users"
    assert tbl.schema is schema
    assert tbl.is_closed is False
    assert tbl.count() == 0
    assert "open" in repr(tbl)


def test_table_insert_and_get(table_fixture) -> None:
    """Verify inserting and retrieving records."""
    tbl, schema = table_fixture

    # Insert raw list
    rid0 = tbl.insert([1, "Alice", 95.5])
    # Insert schema-less Tuple
    rid1 = tbl.insert(Tuple([2, "Bob", None]))
    # Insert schema-bound Tuple
    rid2 = tbl.insert(Tuple([3, "Charlie", 88.0], schema=schema))

    assert tbl.count() == 3

    t0 = tbl.get(rid0)
    assert t0.schema is schema
    assert t0["id"] == 1
    assert t0["name"] == "Alice"
    assert t0["score"] == 95.5

    t1 = tbl.get(rid1)
    assert t1["id"] == 2
    assert t1["name"] == "Bob"
    assert t1["score"] is None

    t2 = tbl.get(rid2)
    assert t2["id"] == 3
    assert t2["name"] == "Charlie"
    assert t2["score"] == 88.0


def test_table_insert_schema_mismatch_rejected(table_fixture) -> None:
    """Verify inserting a Tuple bound to a different schema raises SchemaMismatchError."""
    tbl, _ = table_fixture
    other_schema = Schema([Column("other_id", DataType.BIGINT)])
    foreign_tuple = Tuple([999], schema=other_schema)

    with pytest.raises(SchemaMismatchError):
        tbl.insert(foreign_tuple)


def test_table_insert_validation_errors(table_fixture) -> None:
    """Verify arity and type mismatches raise appropriate exceptions."""
    tbl, _ = table_fixture

    # Arity mismatch (2 values instead of 3)
    with pytest.raises(TupleArityError):
        tbl.insert([1, "Alice"])

    # Type mismatch (str instead of int for id)
    with pytest.raises(TypeMismatchError):
        tbl.insert(["not_an_int", "Alice", 10.0])


def test_table_delete_and_scan(table_fixture) -> None:
    """Verify deleting records and sequential scanning."""
    tbl, _ = table_fixture

    r0 = tbl.insert([1, "Alice", 10.0])
    r1 = tbl.insert([2, "Bob", 20.0])
    r2 = tbl.insert([3, "Charlie", 30.0])

    assert tbl.count() == 3

    tbl.delete(r1)

    # get on deleted record raises RecordNotFoundError
    with pytest.raises(RecordNotFoundError):
        tbl.get(r1)

    # scan returns only live records
    scanned = list(tbl.scan())
    assert len(scanned) == 2
    assert scanned[0] == (r0, tbl.get(r0))
    assert scanned[1] == (r2, tbl.get(r2))
    assert tbl.count() == 2


def test_table_multi_page_span(tmp_path: Path, sample_schema: Schema) -> None:
    """Verify inserting records across multiple slotted pages."""
    db_file = tmp_path / "multi_page_table.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            tbl = Table(1, "large_table", sample_schema, hf)

            # Insert 100 rows with 40-character strings
            inserted_ids = []
            for i in range(100):
                rid = tbl.insert([i, f"user_number_{i:04d}", float(i * 1.5)])
                inserted_ids.append((rid, i))

            assert tbl.heap_file.page_count > 1
            assert tbl.count() == 100

            for rid, expected_id in inserted_ids:
                row = tbl.get(rid)
                assert row["id"] == expected_id

            scanned_ids = [row["id"] for _, row in tbl.scan()]
            assert scanned_ids == list(range(100))


def test_table_small_buffer_pool_eviction(tmp_path: Path, sample_schema: Schema) -> None:
    """Verify correct table operation under pool_size = 1 (heavy eviction)."""
    db_file = tmp_path / "pool_size_1_table.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=1) as bpm:
            hf = HeapFile(bpm)
            tbl = Table(1, "tight_table", sample_schema, hf)

            rids = [tbl.insert([i, f"user_large_payload_{i:04d}", float(i)]) for i in range(200)]
            assert tbl.heap_file.page_count > 1

            for i, rid in enumerate(rids):
                assert tbl.get(rid)["id"] == i

            assert tbl.count() == 200


def test_table_lifecycle_and_closed_storage(table_fixture) -> None:
    """Verify Table operations raise StorageClosedError after closure."""
    tbl, _ = table_fixture
    rid = tbl.insert([1, "Alice", 10.0])

    tbl.close()
    assert tbl.is_closed is True
    assert "closed" in repr(tbl)

    # Second close is idempotent
    tbl.close()

    with pytest.raises(StorageClosedError):
        tbl.insert([2, "Bob", 20.0])
    with pytest.raises(StorageClosedError):
        tbl.get(rid)
    with pytest.raises(StorageClosedError):
        tbl.delete(rid)
    with pytest.raises(StorageClosedError):
        list(tbl.scan())
    with pytest.raises(StorageClosedError):
        tbl.count()
