"""Comprehensive test suite for Strata System Catalog and Persistence (Phase 5).

Validates:
- Catalog bootstrap on brand-new database directory.
- Multi-table isolation across distinct schemas, physical files, and record spaces.
- Monotonic table ID allocation and high-water-mark (HWM) persistence without ID reuse.
- Orphan physical file reconciliation and collision avoidance.
- Table name validation, case-preserving storage, case-insensitive lookups, and reserved '_' names.
- Table dropping, physical file deletion, and stale handle invalidation.
- Manually closed Table eviction and transparent reopening via get_table().
- Full persistence and recovery across catalog close and reopen.
- Exhaustive corruption detection: missing files, corrupt headers, missing table files, bad schemas.
"""

from pathlib import Path
import pytest

from strata_engine.catalog import (
    Catalog,
    CatalogCorruptionError,
    ReservedNameError,
    TableAlreadyExistsError,
    TableNotFoundError,
)
from strata_engine.catalog.catalog import SYSTEM_COLUMNS_SCHEMA, SYSTEM_TABLES_SCHEMA
from strata_engine.schema import (
    Column,
    DataType,
    Schema,
    Tuple,
    TupleSerializer,
)
from strata_engine.storage import (
    BufferPoolManager,
    HeapFile,
    PageFile,
    StorageClosedError,
)


@pytest.fixture
def user_schema() -> Schema:
    return Schema([
        Column("id", DataType.INTEGER, nullable=False),
        Column("name", DataType.VARCHAR, nullable=False, max_length=50),
    ])


@pytest.fixture
def order_schema() -> Schema:
    return Schema([
        Column("order_id", DataType.BIGINT, nullable=False),
        Column("amount", DataType.FLOAT, nullable=False),
        Column("is_paid", DataType.BOOLEAN, nullable=False),
    ])


# ============================================================================
# Bootstrap and Multi-Table Isolation Tests
# ============================================================================


def test_catalog_bootstrap_new_database(tmp_path: Path, user_schema: Schema) -> None:
    """Verify clean catalog bootstrap on a brand-new directory."""
    db_dir = tmp_path / "new_db"
    with Catalog(db_dir) as cat:
        assert (db_dir / "catalog" / "tables.db").exists()
        assert (db_dir / "catalog" / "columns.db").exists()
        assert (db_dir / "tables").exists()
        assert cat.list_tables() == []

        tbl = cat.create_table("users", user_schema)
        assert tbl.table_id == 1
        assert tbl.name == "users"
        assert (db_dir / "tables" / "table_1.db").exists()
        assert cat.list_tables() == ["users"]


def test_multi_table_isolation(tmp_path: Path, user_schema: Schema, order_schema: Schema) -> None:
    """Verify independent operations on tables A and B do not affect each other."""
    db_dir = tmp_path / "multi_table_db"
    with Catalog(db_dir) as cat:
        t_users = cat.create_table("Users", user_schema)
        t_orders = cat.create_table("Orders", order_schema)

        assert t_users.table_id == 1
        assert t_orders.table_id == 2
        assert (db_dir / "tables" / "table_1.db").exists()
        assert (db_dir / "tables" / "table_2.db").exists()

        # Insert records into Users
        u_rid1 = t_users.insert([101, "Alice"])
        u_rid2 = t_users.insert([102, "Bob"])

        # Insert records into Orders
        o_rid1 = t_orders.insert([5001, 19.99, True])
        o_rid2 = t_orders.insert([5002, 49.50, False])
        o_rid3 = t_orders.insert([5003, 100.00, True])

        assert t_users.count() == 2
        assert t_orders.count() == 3

        # Verify records retrieved from each table
        assert t_users.get(u_rid1)["name"] == "Alice"
        assert t_users.get(u_rid2)["name"] == "Bob"

        assert t_orders.get(o_rid1)["amount"] == 19.99
        assert t_orders.get(o_rid2)["is_paid"] is False
        assert t_orders.get(o_rid3)["order_id"] == 5003

        # Scans are completely isolated
        u_rows = [row["id"] for _, row in t_users.scan()]
        o_rows = [row["order_id"] for _, row in t_orders.scan()]
        assert u_rows == [101, 102]
        assert o_rows == [5001, 5002, 5003]


# ============================================================================
# Table Name Rules & Case-Insensitivity
# ============================================================================


def test_table_name_validation_and_reserved_prefix(tmp_path: Path, user_schema: Schema) -> None:
    """Verify reserved '_' prefix rejection and duplicate name handling."""
    with Catalog(tmp_path / "name_db") as cat:
        # Names starting with '_' are reserved
        with pytest.raises(ReservedNameError):
            cat.create_table("_users", user_schema)
        with pytest.raises(ReservedNameError):
            cat.create_table("_tables", user_schema)

        # Valid creation with case preserved
        t = cat.create_table("UserProfile", user_schema)
        assert t.name == "UserProfile"
        assert cat.list_tables() == ["UserProfile"]

        # Duplicate case-insensitive creation rejected
        with pytest.raises(TableAlreadyExistsError) as exc_info:
            cat.create_table("userprofile", user_schema)
        assert "userprofile" in str(exc_info.value)
        assert "UserProfile" in str(exc_info.value)

        # Lookups are case-insensitive
        assert cat.has_table("userprofile") is True
        assert cat.has_table("USERPROFILE") is True
        assert cat.has_table("UserProfile") is True
        assert cat.get_table("userprofile") is t
        assert cat.get_table("USERPROFILE") is t

        # System tables are not accessible via get_table
        with pytest.raises(TableNotFoundError):
            cat.get_table("_tables")


# ============================================================================
# Table Drop & Stale Handle Invalidation
# ============================================================================


def test_table_drop_and_handle_invalidation(tmp_path: Path, user_schema: Schema) -> None:
    """Verify drop_table removes metadata, disk file, and invalidates old Table handles."""
    db_dir = tmp_path / "drop_db"
    with Catalog(db_dir) as cat:
        t = cat.create_table("users", user_schema)
        t_file = db_dir / "tables" / "table_1.db"
        assert t_file.exists()

        rid = t.insert([1, "Alice"])
        assert t.get(rid)["name"] == "Alice"

        cat.drop_table("users")

        # Logical table is gone
        assert cat.has_table("users") is False
        assert cat.list_tables() == []
        with pytest.raises(TableNotFoundError):
            cat.get_table("users")

        # Backing file on disk is deleted
        assert not t_file.exists()

        # Stale Table handle is closed and rejects access
        assert t.is_closed is True
        with pytest.raises(StorageClosedError):
            t.insert([2, "Bob"])
        with pytest.raises(StorageClosedError):
            t.get(rid)


def test_manually_closed_table_reopened_transparently(tmp_path: Path, user_schema: Schema) -> None:
    """Verify manually closed Table is evicted and reopened cleanly upon get_table()."""
    with Catalog(tmp_path / "reopen_table_db") as cat:
        t1 = cat.get_table("users") if cat.has_table("users") else cat.create_table("users", user_schema)
        rid = t1.insert([1, "Alice"])

        # Manually close t1
        t1.close()
        assert t1.is_closed is True

        # Calling get_table retrieves a fresh, open Table instance
        t2 = cat.get_table("users")
        assert t2 is not t1
        assert t2.is_closed is False
        assert t2.get(rid)["name"] == "Alice"


# ============================================================================
# High-Water-Mark (HWM) and Table ID Monotonicity
# ============================================================================


def test_hwm_monotonicity_no_id_reuse_after_drop(tmp_path: Path, user_schema: Schema) -> None:
    """Verify table IDs are never reused even after dropping tables and reopening catalog."""
    db_dir = tmp_path / "hwm_db"

    # Session 1: create tables 1 and 2, drop table 2
    with Catalog(db_dir) as cat1:
        t1 = cat1.create_table("users", user_schema)
        assert t1.table_id == 1

        t2 = cat1.create_table("orders", user_schema)
        assert t2.table_id == 2

        cat1.drop_table("orders")
        assert cat1.list_tables() == ["users"]

    # Session 2: reopen catalog; next table MUST receive ID 3 (not 2!)
    with Catalog(db_dir) as cat2:
        assert cat2.list_tables() == ["users"]
        t3 = cat2.create_table("products", user_schema)
        assert t3.table_id == 3
        assert (db_dir / "tables" / "table_3.db").exists()


def test_hwm_reconciliation_with_orphan_physical_files(tmp_path: Path, user_schema: Schema) -> None:
    """Verify orphan table_N.db files advance HWM to avoid filename collisions."""
    db_dir = tmp_path / "orphan_hwm_db"

    with Catalog(db_dir) as cat1:
        t1 = cat1.create_table("t1", user_schema)
        t2 = cat1.create_table("t2", user_schema)
        assert t1.table_id == 1
        assert t2.table_id == 2

    # Simulate orphan file table_5.db created by crash/external process
    orphan_file = db_dir / "tables" / "table_5.db"
    with PageFile(orphan_file) as pf:
        pf.allocate_page()

    # Create arbitrary non-matching files (must be ignored)
    (db_dir / "tables" / "table_foo.db").write_text("ignore")
    (db_dir / "tables" / "temp.dat").write_text("ignore")

    with Catalog(db_dir) as cat2:
        # Candidate ID must skip past 5 to 6
        t_new = cat2.create_table("t_new", user_schema)
        assert t_new.table_id == 6
        assert (db_dir / "tables" / "table_6.db").exists()


# ============================================================================
# Full Persistence and Reopen Tests
# ============================================================================


def test_catalog_persistence_round_trip(tmp_path: Path, user_schema: Schema, order_schema: Schema) -> None:
    """Verify table definitions and data survive complete engine shutdown and restart."""
    db_dir = tmp_path / "persistent_db"

    # Session 1: Populate database
    with Catalog(db_dir) as cat1:
        u_tbl = cat1.create_table("users", user_schema)
        o_tbl = cat1.create_table("orders", order_schema)

        u_tbl.insert([1, "Alice"])
        u_tbl.insert([2, "Bob"])

        o_tbl.insert([1001, 15.50, True])
        o_tbl.insert([1002, 29.99, False])

    # Session 2: Reopen from disk
    with Catalog(db_dir) as cat2:
        assert set(cat2.list_tables()) == {"users", "orders"}

        u_recovered = cat2.get_table("users")
        assert u_recovered.table_id == 1
        assert u_recovered.schema.fingerprint == user_schema.fingerprint
        assert u_recovered.count() == 2

        u_data = [row.values for _, row in u_recovered.scan()]
        assert u_data == [(1, "Alice"), (2, "Bob")]

        o_recovered = cat2.get_table("orders")
        assert o_recovered.table_id == 2
        assert o_recovered.schema.fingerprint == order_schema.fingerprint
        assert o_recovered.count() == 2

        o_data = [row.values for _, row in o_recovered.scan()]
        assert o_data == [(1001, 15.50, True), (1002, 29.99, False)]


# ============================================================================
# Corruption Detection Tests
# ============================================================================


def test_corruption_partial_catalog_files(tmp_path: Path) -> None:
    """Verify CatalogCorruptionError if only one catalog file exists."""
    db_dir = tmp_path / "partial_db"
    (db_dir / "catalog").mkdir(parents=True)

    # Only tables.db exists
    (db_dir / "catalog" / "tables.db").touch()
    with pytest.raises(CatalogCorruptionError):
        Catalog(db_dir)

    # Only columns.db exists
    (db_dir / "catalog" / "tables.db").unlink()
    (db_dir / "catalog" / "columns.db").touch()
    with pytest.raises(CatalogCorruptionError):
        Catalog(db_dir)


def test_corruption_missing_or_duplicate_header(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError if catalog header record is missing or duplicate."""
    db_dir = tmp_path / "corrupt_hdr_db"

    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    # Open tables.db directly and tamper with header (table_id = 0)
    tables_path = db_dir / "catalog" / "tables.db"
    with PageFile(tables_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            # Find and delete header record
            for rid, raw in list(hf.scan_records()):
                row = TupleSerializer(SYSTEM_TABLES_SCHEMA).deserialize(raw)
                if row[0] == 0:
                    hf.delete_record(rid)
            bpm.flush_all()

    # Reopen must fail because header is missing
    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Expected exactly one catalog header record" in str(exc_info.value)


def test_corruption_missing_physical_table_file(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError if a registered table's physical file is deleted."""
    db_dir = tmp_path / "missing_file_db"

    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    # Delete physical file table_1.db
    (db_dir / "tables" / "table_1.db").unlink()

    # Reopening must raise CatalogCorruptionError
    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Physical storage file" in str(exc_info.value)
    assert "missing" in str(exc_info.value)


def test_corruption_table_without_columns(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError if a table in tables.db has no columns in columns.db."""
    db_dir = tmp_path / "no_cols_db"

    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    # Wipe columns.db records
    cols_path = db_dir / "catalog" / "columns.db"
    with PageFile(cols_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            for rid, _ in list(hf.scan_records()):
                hf.delete_record(rid)
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "has no column records" in str(exc_info.value)


def test_corruption_duplicate_header(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError if tables.db contains multiple header records."""
    db_dir = tmp_path / "dup_hdr_db"
    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    tables_path = db_dir / "catalog" / "tables.db"
    with PageFile(tables_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            # Insert a second header record (table_id = 0)
            dup_hdr = Tuple([0, "STRATA_CATALOG_V1:HWM=99"], SYSTEM_TABLES_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_TABLES_SCHEMA).serialize(dup_hdr))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Expected exactly one catalog header record" in str(exc_info.value)


def test_corruption_malformed_or_negative_hwm(tmp_path: Path) -> None:
    """Verify CatalogCorruptionError on malformed or negative HWM in header."""
    db_dir = tmp_path / "bad_hwm_db"
    with Catalog(db_dir):
        pass

    tables_path = db_dir / "catalog" / "tables.db"
    with PageFile(tables_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            for rid, raw in list(hf.scan_records()):
                hf.delete_record(rid)
            bad_hdr = Tuple([0, "STRATA_CATALOG_V1:HWM=-5"], SYSTEM_TABLES_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_TABLES_SCHEMA).serialize(bad_hdr))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Malformed catalog HWM" in str(exc_info.value)


def test_corruption_duplicate_table_id(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError when tables.db has duplicate table IDs."""
    db_dir = tmp_path / "dup_id_db"
    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    tables_path = db_dir / "catalog" / "tables.db"
    with PageFile(tables_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            dup_rec = Tuple([1, "users_dup"], SYSTEM_TABLES_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_TABLES_SCHEMA).serialize(dup_rec))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Duplicate table ID 1" in str(exc_info.value)


def test_corruption_duplicate_case_insensitive_table_names(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError when tables.db has duplicate names case-insensitively."""
    db_dir = tmp_path / "dup_name_db"
    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    tables_path = db_dir / "catalog" / "tables.db"
    with PageFile(tables_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            dup_name_rec = Tuple([2, "USERS"], SYSTEM_TABLES_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_TABLES_SCHEMA).serialize(dup_name_rec))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Duplicate case-insensitive table name" in str(exc_info.value)


def test_corruption_non_contiguous_ordinals(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError when column ordinals have gaps."""
    db_dir = tmp_path / "ordinal_gap_db"
    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    cols_path = db_dir / "catalog" / "columns.db"
    with PageFile(cols_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            for rid, _ in list(hf.scan_records()):
                hf.delete_record(rid)
            # Insert columns with ordinals 0 and 2 (gap: 1 missing)
            c0 = Tuple([1, "c0", 0, "INTEGER", False, None], SYSTEM_COLUMNS_SCHEMA)
            c2 = Tuple([1, "c2", 2, "INTEGER", False, None], SYSTEM_COLUMNS_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_COLUMNS_SCHEMA).serialize(c0))
            hf.insert_record(TupleSerializer(SYSTEM_COLUMNS_SCHEMA).serialize(c2))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "invalid or non-contiguous ordinals" in str(exc_info.value)


def test_corruption_unknown_data_type(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError when column record has unknown DataType."""
    db_dir = tmp_path / "unknown_dt_db"
    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    cols_path = db_dir / "catalog" / "columns.db"
    with PageFile(cols_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            for rid, _ in list(hf.scan_records()):
                hf.delete_record(rid)
            bad_col = Tuple([1, "bad", 0, "UNKNOWN_TYPE", False, None], SYSTEM_COLUMNS_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_COLUMNS_SCHEMA).serialize(bad_col))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "unrecognized DataType" in str(exc_info.value)


def test_corruption_invalid_varchar_max_length(tmp_path: Path, user_schema: Schema) -> None:
    """Verify CatalogCorruptionError when VARCHAR column record has invalid max_length."""
    db_dir = tmp_path / "bad_len_db"
    with Catalog(db_dir) as cat:
        cat.create_table("users", user_schema)

    cols_path = db_dir / "catalog" / "columns.db"
    with PageFile(cols_path) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            for rid, _ in list(hf.scan_records()):
                hf.delete_record(rid)
            # max_length = 5000 > 4080
            bad_col = Tuple([1, "name", 0, "VARCHAR", False, 5000], SYSTEM_COLUMNS_SCHEMA)
            hf.insert_record(TupleSerializer(SYSTEM_COLUMNS_SCHEMA).serialize(bad_col))
            bpm.flush_all()

    with pytest.raises(CatalogCorruptionError) as exc_info:
        Catalog(db_dir)
    assert "Corrupt column definition" in str(exc_info.value)

