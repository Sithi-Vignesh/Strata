"""Comprehensive test suite for Phase 4: HeapFile Record Storage.

Validates:
- Construction, property access, and StorageClosedError enforcement.
- Record insertion across single and multiple slotted pages.
- Variable-length records, live empty records (b""), and exact-fit records (4084 bytes).
- Oversized record rejection (> 4084 bytes) with zero phantom page allocations.
- Record retrieval (get_record) across single and multiple pages.
- Record deletion, deleted-slot reuse, and deletion error handling.
- Deterministic cross-page scanning (scan_records) with per-page unpinning.
- Early break from scan iterator with zero pinned pages leaked.
- Heavy buffer pool eviction with pool_size = 1 and pool_size = 2.
- Multi-page persistence and recovery across database close and reopen.
"""

from pathlib import Path
import pytest

from strata_engine.storage import (
    PAGE_SIZE,
    BufferPoolManager,
    HeapFile,
    PageFile,
    PageId,
    RecordId,
    RecordNotFoundError,
    RecordSizeError,
    StorageClosedError,
)
from strata_engine.storage.slotted_page import MAX_RECORD_SIZE


# ============================================================================
# Construction and Property Tests
# ============================================================================


def test_heap_file_init_valid(tmp_path: Path) -> None:
    """Verify valid HeapFile initialization and initial properties."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=5)
        hf = HeapFile(bpm)

        assert hf.buffer_pool_manager is bpm
        assert hf.page_count == 0
        assert "pages=0" in repr(hf)
        assert "open" in repr(hf)


def test_heap_file_init_invalid_type() -> None:
    """Verify non-BufferPoolManager argument raises TypeError."""
    with pytest.raises(TypeError) as exc_info:
        HeapFile("not_a_bpm")  # type: ignore[arg-type]
    assert "Expected BufferPoolManager" in str(exc_info.value)


def test_heap_file_init_closed_bpm(tmp_path: Path) -> None:
    """Verify initializing HeapFile on closed BufferPoolManager raises StorageClosedError."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=5)
        bpm.close()

        with pytest.raises(StorageClosedError):
            HeapFile(bpm)


def test_heap_file_operations_on_closed_storage(tmp_path: Path) -> None:
    """Verify HeapFile operations raise StorageClosedError once BPM or PageFile is closed."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=5)
        hf = HeapFile(bpm)
        rid = hf.insert_record(b"Initial record")

        bpm.close()

        with pytest.raises(StorageClosedError):
            hf.insert_record(b"Fail record")
        with pytest.raises(StorageClosedError):
            hf.get_record(rid)
        with pytest.raises(StorageClosedError):
            hf.delete_record(rid)
        with pytest.raises(StorageClosedError):
            list(hf.scan_records())


# ============================================================================
# Record Insertion Tests
# ============================================================================


def test_insert_first_record_allocates_page_zero(tmp_path: Path) -> None:
    """Verify inserting the first record on an empty heap allocates PageId(0)."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            assert hf.page_count == 0

            rid = hf.insert_record(b"First record payload")
            assert rid.page_id == PageId(0)
            assert rid.slot_id == 0
            assert hf.page_count == 1
            assert hf.get_record(rid) == b"First record payload"


def test_insert_multiple_records_on_single_page(tmp_path: Path) -> None:
    """Verify multiple records fit on the same page without allocating new pages."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rids = []
            for i in range(5):
                rid = hf.insert_record(f"Record {i}".encode("utf-8"))
                rids.append(rid)

            assert hf.page_count == 1
            for i, rid in enumerate(rids):
                assert rid.page_id == PageId(0)
                assert rid.slot_id == i
                assert hf.get_record(rid) == f"Record {i}".encode("utf-8")


def test_insert_empty_record(tmp_path: Path) -> None:
    """Verify live empty record (b"") can be inserted, retrieved, and scanned."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rid = hf.insert_record(b"")
            assert hf.get_record(rid) == b""

            scanned = list(hf.scan_records())
            assert len(scanned) == 1
            assert scanned[0] == (rid, b"")


def test_insert_invalid_type_raises_type_error(tmp_path: Path) -> None:
    """Verify non-bytes record data raises TypeError."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            with pytest.raises(TypeError):
                hf.insert_record("string not bytes")  # type: ignore[arg-type]


def test_insert_exact_fit_record(tmp_path: Path) -> None:
    """Verify inserting exact maximum record size (4084 bytes) completely packs the page."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            exact_data = b"X" * MAX_RECORD_SIZE
            rid = hf.insert_record(exact_data)

            assert rid == RecordId(0, 0)
            assert hf.page_count == 1
            assert hf.get_record(rid) == exact_data

            # Next insert must allocate PageId(1) because Page 0 has exactly 0 free bytes
            rid2 = hf.insert_record(b"Next page record")
            assert rid2.page_id == PageId(1)
            assert rid2.slot_id == 0
            assert hf.page_count == 2


def test_insert_oversized_record_fails_without_allocating_page(tmp_path: Path) -> None:
    """Verify oversized record (> 4084 bytes) raises RecordSizeError without allocating a page."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            oversized = b"O" * (MAX_RECORD_SIZE + 1)

            with pytest.raises(RecordSizeError) as exc_info:
                hf.insert_record(oversized)
            assert f"exceeds maximum page capacity of {MAX_RECORD_SIZE}" in str(exc_info.value)

            # Invariant: No phantom page was allocated!
            assert hf.page_count == 0


def test_insert_page_filling_allocates_multiple_pages(tmp_path: Path) -> None:
    """Verify sequential inserts automatically allocate new pages when space is exhausted."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            chunk = b"A" * 1000  # Each page holds at most 4 chunks (4 * 1004 = 4016 bytes <= 4088)

            rids = []
            for _ in range(10):  # 10 records of 1000 bytes will span at least 3 pages
                rids.append(hf.insert_record(chunk))

            assert hf.page_count >= 3
            # Check all records are retrievable
            for rid in rids:
                assert hf.get_record(rid) == chunk


# ============================================================================
# Record Retrieval (get_record) Tests
# ============================================================================


def test_get_record_invalid_type(tmp_path: Path) -> None:
    """Verify get_record raises TypeError if not given RecordId."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            with pytest.raises(TypeError):
                hf.get_record((0, 0))  # type: ignore[arg-type]


def test_get_record_not_found(tmp_path: Path) -> None:
    """Verify get_record on unallocated slot or deleted slot raises expected storage errors."""
    from strata_engine.storage import InvalidSlotIdError, PageNotFoundError

    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rid = hf.insert_record(b"Existing record")

            # Deleted slot raises RecordNotFoundError
            hf.delete_record(rid)
            with pytest.raises(RecordNotFoundError):
                hf.get_record(rid)

            # Slot 99 does not exist in slot directory on page 0
            with pytest.raises(InvalidSlotIdError):
                hf.get_record(RecordId(0, 99))

            # Page 5 does not exist in storage file
            with pytest.raises(PageNotFoundError):
                hf.get_record(RecordId(5, 0))



# ============================================================================
# Record Deletion Tests
# ============================================================================


def test_delete_record_success(tmp_path: Path) -> None:
    """Verify deleting a record marks it deleted and subsequent get raises RecordNotFoundError."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rid1 = hf.insert_record(b"Record 1")
            rid2 = hf.insert_record(b"Record 2")

            hf.delete_record(rid1)

            with pytest.raises(RecordNotFoundError):
                hf.get_record(rid1)

            # rid2 remains intact
            assert hf.get_record(rid2) == b"Record 2"


def test_delete_record_repeated_raises_error(tmp_path: Path) -> None:
    """Verify deleting an already deleted record raises RecordNotFoundError."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rid = hf.insert_record(b"Payload")
            hf.delete_record(rid)

            with pytest.raises(RecordNotFoundError):
                hf.delete_record(rid)


def test_delete_record_slot_reuse(tmp_path: Path) -> None:
    """Verify deleting a slot allows subsequent insert to reuse that slot ID."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rid0 = hf.insert_record(b"Zero")
            rid1 = hf.insert_record(b"One")
            rid2 = hf.insert_record(b"Two")

            # Delete rid1 (slot 1 on page 0)
            hf.delete_record(rid1)

            # Insert new record; SlottedPage reuses slot 1
            new_rid = hf.insert_record(b"New One")
            assert new_rid == rid1  # Same RecordId(0, 1)
            assert hf.get_record(new_rid) == b"New One"


def test_delete_sole_record_keeps_page_allocated(tmp_path: Path) -> None:
    """Verify deleting the only record on a page leaves page allocated without crashing."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            rid = hf.insert_record(b"Sole record")
            assert hf.page_count == 1

            hf.delete_record(rid)
            assert hf.page_count == 1

            # Scanning returns empty
            assert list(hf.scan_records()) == []


# ============================================================================
# Scanning (scan_records) Tests
# ============================================================================


def test_scan_records_empty_heap(tmp_path: Path) -> None:
    """Verify scanning an empty heap yields zero items."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)
            assert list(hf.scan_records()) == []


def test_scan_records_deterministic_ordering_and_deletion_skipping(tmp_path: Path) -> None:
    """Verify scan visits PageId ascending, slot_id ascending, and skips deleted slots."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=5) as bpm:
            hf = HeapFile(bpm)

            # Insert records that span multiple pages
            chunk = b"X" * 1500  # ~2 per page
            rids = []
            for i in range(5):
                rids.append(hf.insert_record(chunk + f"_{i}".encode()))

            assert hf.page_count >= 3

            # Delete record at index 1
            hf.delete_record(rids[1])

            # Scan
            scanned = list(hf.scan_records())
            scanned_rids = [rid for rid, _ in scanned]

            expected_rids = [rids[0], rids[2], rids[3], rids[4]]
            assert scanned_rids == expected_rids

            # Verify contents
            for rid, data in scanned:
                assert data == hf.get_record(rid)


def test_scan_records_early_break_no_pin_leak(tmp_path: Path) -> None:
    """Verify breaking early from scan_records generator leaves zero frames pinned."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=3) as bpm:
            hf = HeapFile(bpm)
            for i in range(10):
                hf.insert_record(f"Record {i}".encode())

            # Start scan and break after 2 items
            count = 0
            for rid, data in hf.scan_records():
                count += 1
                if count == 2:
                    break

            # Invariant: No frame must remain pinned in the buffer pool!
            for frame in bpm._frames:
                assert frame.pin_count == 0, f"Frame {frame.frame_id} leaked pin: pin_count={frame.pin_count}"


# ============================================================================
# Buffer Pool Eviction & pool_size = 1 / pool_size = 2 Integration Tests
# ============================================================================


def test_heap_file_with_pool_size_one(tmp_path: Path) -> None:
    """Crucial integration test: Verify HeapFile operates completely under pool_size = 1."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=1) as bpm:
            hf = HeapFile(bpm)

            # Insert records requiring at least 3 pages with only 1 buffer frame!
            # Every record is 2500 bytes (> 2044 bytes, so at most 1 fits per page).
            # Every new page forces eviction of the previous page.
            chunk = b"P" * 2500
            r0 = hf.insert_record(chunk + b"_0")
            r1 = hf.insert_record(chunk + b"_1")
            r2 = hf.insert_record(chunk + b"_2")

            assert hf.page_count == 3
            assert r0.page_id == PageId(0)
            assert r1.page_id == PageId(1)
            assert r2.page_id == PageId(2)

            # Fetching r0 evicts r2
            assert hf.get_record(r0) == chunk + b"_0"

            # Fetching r1 evicts r0
            assert hf.get_record(r1) == chunk + b"_1"

            # Fetching r2 evicts r1
            assert hf.get_record(r2) == chunk + b"_2"

            # Scanning all records across 3 pages with pool_size = 1!
            scanned = list(hf.scan_records())
            assert len(scanned) == 3
            assert [rid for rid, _ in scanned] == [r0, r1, r2]

            # Verify no frame is pinned
            assert bpm._frames[0].pin_count == 0


def test_heap_file_with_pool_size_two_heavy_eviction(tmp_path: Path) -> None:
    """Verify multi-page operations under pool_size = 2 with frequent eviction."""
    db_file = tmp_path / "heap_test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=2) as bpm:
            hf = HeapFile(bpm)
            rids = []
            chunk = b"Record payload ".ljust(1500, b"X")
            for i in range(12):
                rids.append(hf.insert_record(chunk + f"_{i}".encode()))

            # 12 records of 1500 bytes (at most 2 per page) occupy 6 pages
            assert hf.page_count >= 4

            # Verify all records can be retrieved despite buffer capacity 2
            for i, rid in enumerate(rids):
                assert hf.get_record(rid) == chunk + f"_{i}".encode()

            # Verify scan
            scanned = list(hf.scan_records())
            assert len(scanned) == 12

            for frame in bpm._frames:
                assert frame.pin_count == 0


# ============================================================================
# Multi-Page Persistence Across Reopen Tests
# ============================================================================


def test_heap_file_persistence_across_reopen(tmp_path: Path) -> None:
    """Verify records inserted across multiple pages survive file close and reopen."""
    db_file = tmp_path / "persistent_heap.db"

    inserted_records = {}

    # Phase 1: Create, populate, and close
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=2) as bpm:
            hf = HeapFile(bpm)
            chunk = b"Persistent task details ".ljust(1000, b"Z")
            for i in range(15):
                payload = chunk + f"_{i}".encode()
                rid = hf.insert_record(payload)
                inserted_records[rid] = payload

            # 15 records of 1000 bytes occupy at least 4 pages
            assert hf.page_count >= 3

    # Phase 2: Reopen from disk with a fresh BufferPoolManager and HeapFile
    with PageFile(db_file) as pf_reopened:
        with BufferPoolManager(pf_reopened, pool_size=2) as bpm_reopened:
            hf_reopened = HeapFile(bpm_reopened)

            assert hf_reopened.page_count >= 3

            # Verify individual gets
            for rid, expected_data in inserted_records.items():
                assert hf_reopened.get_record(rid) == expected_data

            # Verify full scan
            scanned = list(hf_reopened.scan_records())
            assert len(scanned) == 15
            for rid, data in scanned:
                assert inserted_records[rid] == data

