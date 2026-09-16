"""Comprehensive test suite for Phase 2: Record and Slotted-Page Storage Layer.

Validates:
- Empty slotted page creation, header serialization, and parsing invariants.
- RecordId validation, comparisons, hashing, and representation.
- Variable-length record insertion, retrieval, and empty record handling.
- Maximum record size boundaries and InsufficientSpaceError.
- Record deletion, deletion idempotency / errors, and deleted slot reuse.
- Defragmentation compaction, preservation of live records, and stable slot IDs.
- Structural corruption detection (magic number, boundary violations, overlapping records).
- End-to-end integration and persistence across PageFile write, close, reopen, and read.
"""

from pathlib import Path
import struct
import pytest

from strata_engine.storage import (
    PAGE_SIZE,
    InsufficientSpaceError,
    InvalidPageIdError,
    InvalidSlotIdError,
    Page,
    PageFile,
    PageId,
    PageNotFoundError,
    PageSizeError,
    RecordId,
    RecordNotFoundError,
    RecordSizeError,
    SlottedPage,
    SlottedPageCorruptionError,
)
from strata_engine.storage.slotted_page import (
    PAGE_HEADER_MAGIC,
    PAGE_HEADER_SIZE,
    SLOT_ENTRY_SIZE,
)


# ============================================================================
# RecordId Tests
# ============================================================================


def test_record_id_valid() -> None:
    """Verify valid construction of RecordId."""
    rid = RecordId(0, 5)
    assert int(rid.page_id) == 0
    assert rid.slot_id == 5
    assert repr(rid) == "RecordId(page_id=0, slot_id=5)"
    assert str(rid) == "(0, 5)"

    rid2 = RecordId(PageId(3), 0)
    assert int(rid2.page_id) == 3
    assert rid2.slot_id == 0


def test_record_id_rejection_negative_slot() -> None:
    """Verify negative slot IDs raise InvalidSlotIdError."""
    with pytest.raises(InvalidSlotIdError):
        RecordId(0, -1)


@pytest.mark.parametrize("invalid_slot", [True, False, 1.5, "0", None, []])
def test_record_id_rejection_invalid_slot_types(invalid_slot: object) -> None:
    """Verify booleans, floats, strings, and non-ints raise InvalidSlotIdError."""
    with pytest.raises(InvalidSlotIdError):
        RecordId(0, invalid_slot)  # type: ignore[arg-type]


def test_record_id_rejection_invalid_page_id() -> None:
    """Verify invalid page IDs raise InvalidPageIdError."""
    with pytest.raises(InvalidPageIdError):
        RecordId(-1, 0)
    with pytest.raises(InvalidPageIdError):
        RecordId("0", 0)  # type: ignore[arg-type]


def test_record_id_equality_and_hashing() -> None:
    """Verify RecordId equality and set/dict hashing."""
    r1 = RecordId(1, 2)
    r2 = RecordId(PageId(1), 2)
    r3 = RecordId(1, 3)
    r4 = RecordId(2, 2)

    assert r1 == r2
    assert r1 != r3
    assert r1 != r4

    s = {r1, r2, r3}
    assert len(s) == 2
    assert r2 in s


# ============================================================================
# SlottedPage Creation & Header Tests
# ============================================================================


def test_empty_slotted_page_creation() -> None:
    """Verify a newly initialized slotted page has valid header and 0 slots."""
    sp = SlottedPage(page_id=0)
    assert sp.slot_count == 0
    assert sp.live_record_count == 0
    assert sp.free_space_offset == PAGE_SIZE
    assert sp.slot_directory_end == PAGE_HEADER_SIZE
    assert sp.contiguous_free_space_bytes == PAGE_SIZE - PAGE_HEADER_SIZE
    assert sp.total_free_space_bytes == PAGE_SIZE - PAGE_HEADER_SIZE

    page_bytes = sp.to_bytes()
    assert len(page_bytes) == PAGE_SIZE

    # Verify header magic
    magic = struct.unpack_from(">H", page_bytes, 0)[0]
    assert magic == PAGE_HEADER_MAGIC


def test_slotted_page_to_page_and_from_page() -> None:
    """Verify roundtrip conversion between SlottedPage and Page."""
    sp1 = SlottedPage(page_id=2)
    sp1.insert_record(b"Record Alpha")
    sp1.insert_record(b"Record Beta")

    page = sp1.to_page()
    assert isinstance(page, Page)
    assert len(page) == PAGE_SIZE

    sp2 = SlottedPage.from_page(page, page_id=2)
    assert sp2.slot_count == 2
    assert sp2.live_record_count == 2
    assert sp2.get_record(0) == b"Record Alpha"
    assert sp2.get_record(1) == b"Record Beta"


def test_slotted_page_rejection_invalid_size() -> None:
    """Verify passing invalid length buffers raises PageSizeError."""
    with pytest.raises(PageSizeError):
        SlottedPage(data=b"X" * 100)


# ============================================================================
# Record Insertion & Retrieval Tests
# ============================================================================


def test_insert_and_retrieve_single_record() -> None:
    """Verify inserting and retrieving a single record."""
    sp = SlottedPage()
    slot_id = sp.insert_record(b"Hello World")
    assert slot_id == 0
    assert sp.slot_count == 1
    assert sp.live_record_count == 1

    retrieved = sp.get_record(0)
    assert retrieved == b"Hello World"


def test_insert_and_retrieve_multiple_variable_length_records() -> None:
    """Verify inserting multiple records of different sizes."""
    sp = SlottedPage()
    records = [
        b"A" * 10,
        b"B" * 500,
        b"C" * 1,
        b"D" * 2048,
        b"E" * 100,
    ]

    slot_ids = [sp.insert_record(rec) for rec in records]
    assert slot_ids == [0, 1, 2, 3, 4]
    assert sp.slot_count == 5
    assert sp.live_record_count == 5

    for sid, original in zip(slot_ids, records):
        assert sp.get_record(sid) == original


def test_insert_and_retrieve_empty_record() -> None:
    """Verify inserting an empty record (0 bytes) functions properly."""
    sp = SlottedPage()
    slot_id = sp.insert_record(b"")
    assert slot_id == 0
    assert sp.slot_count == 1
    assert sp.live_record_count == 1

    retrieved = sp.get_record(0)
    assert retrieved == b""


def test_insert_invalid_type_raises_type_error() -> None:
    """Verify non-bytes data raises TypeError."""
    sp = SlottedPage()
    with pytest.raises(TypeError):
        sp.insert_record("Not bytes")  # type: ignore[arg-type]


def test_record_size_error_on_too_large() -> None:
    """Verify records exceeding maximum possible page capacity raise RecordSizeError."""
    sp = SlottedPage()
    oversized = b"Z" * (PAGE_SIZE - PAGE_HEADER_SIZE - SLOT_ENTRY_SIZE + 1)
    with pytest.raises(RecordSizeError):
        sp.insert_record(oversized)


def test_insufficient_space_error() -> None:
    """Verify inserting records until page is full raises InsufficientSpaceError."""
    sp = SlottedPage()
    # Insert a large record of 3000 bytes
    sp.insert_record(b"X" * 3000)

    # Try inserting another 2000-byte record (only ~1080 bytes left)
    with pytest.raises(InsufficientSpaceError) as exc_info:
        sp.insert_record(b"Y" * 2000)
    assert "Insufficient space" in str(exc_info.value)


# ============================================================================
# Retrieval & Slot ID Error Tests
# ============================================================================


def test_get_record_invalid_slot_id() -> None:
    """Verify invalid slot IDs raise InvalidSlotIdError."""
    sp = SlottedPage()
    sp.insert_record(b"First")

    with pytest.raises(InvalidSlotIdError):
        sp.get_record(-1)

    with pytest.raises(InvalidSlotIdError):
        sp.get_record(1)  # out of range (only slot 0 exists)

    with pytest.raises(InvalidSlotIdError):
        sp.get_record(True)  # type: ignore[arg-type]


# ============================================================================
# Record Deletion Tests
# ============================================================================


def test_delete_record_success() -> None:
    """Verify deleting a record marks it as deleted and unretrievable."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"Record 0")
    s1 = sp.insert_record(b"Record 1")
    s2 = sp.insert_record(b"Record 2")

    assert sp.live_record_count == 3
    sp.delete_record(s1)

    assert sp.slot_count == 3  # total slots unchanged
    assert sp.live_record_count == 2

    assert sp.get_record(s0) == b"Record 0"
    assert sp.get_record(s2) == b"Record 2"

    with pytest.raises(RecordNotFoundError):
        sp.get_record(s1)


def test_delete_already_deleted_record_raises_error() -> None:
    """Verify attempting to delete an already deleted record raises RecordNotFoundError."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"Record 0")
    sp.delete_record(s0)

    with pytest.raises(RecordNotFoundError) as exc_info:
        sp.delete_record(s0)
    assert "already deleted" in str(exc_info.value)


def test_delete_invalid_slot_id() -> None:
    """Verify deleting out-of-range or invalid slot IDs raises InvalidSlotIdError."""
    sp = SlottedPage()
    with pytest.raises(InvalidSlotIdError):
        sp.delete_record(0)

    with pytest.raises(InvalidSlotIdError):
        sp.delete_record(-1)


def test_slot_reuse_after_deletion() -> None:
    """Verify inserting a new record reuses a previously deleted slot."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"Record 0")
    s1 = sp.insert_record(b"Record 1")
    s2 = sp.insert_record(b"Record 2")

    sp.delete_record(s1)

    # Insert a new record; it should reuse slot s1
    reused_slot = sp.insert_record(b"New Record in Slot 1")
    assert reused_slot == s1
    assert sp.slot_count == 3
    assert sp.live_record_count == 3
    assert sp.get_record(s1) == b"New Record in Slot 1"


# ============================================================================
# Fragmentation and Compaction Tests
# ============================================================================


def test_fragmentation_and_compaction() -> None:
    """Verify page compaction defragments dead space and preserves live records."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"0" * 500)
    s1 = sp.insert_record(b"1" * 500)
    s2 = sp.insert_record(b"2" * 500)
    s3 = sp.insert_record(b"3" * 500)

    free_before_delete = sp.contiguous_free_space_bytes

    # Delete s1 and s2
    sp.delete_record(s1)
    sp.delete_record(s2)

    # Contiguous free space has not changed because holes are between s0 and s3
    assert sp.contiguous_free_space_bytes == free_before_delete
    assert sp.total_free_space_bytes == free_before_delete + 1000

    # Compact the page
    sp.compact()

    # Contiguous free space should now equal total free space
    assert sp.contiguous_free_space_bytes == free_before_delete + 1000

    # Live records are preserved with identical slot IDs
    assert sp.get_record(s0) == b"0" * 500
    assert sp.get_record(s3) == b"3" * 500
    with pytest.raises(RecordNotFoundError):
        sp.get_record(s1)
    with pytest.raises(RecordNotFoundError):
        sp.get_record(s2)


def test_automatic_compaction_on_insertion() -> None:
    """Verify inserting a record that fits in total free space triggers compaction."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"A" * 1500)
    s1 = sp.insert_record(b"B" * 1500)
    s2 = sp.insert_record(b"C" * 800)

    # Delete s1 (1500 bytes becomes fragmented)
    sp.delete_record(s1)

    # Contiguous space is currently ~200 bytes, but total free space is ~1700 bytes
    assert sp.contiguous_free_space_bytes < 1000
    assert sp.total_free_space_bytes > 1200

    # Inserting an 1100-byte record requires automatic compaction
    s_new = sp.insert_record(b"D" * 1100)
    assert s_new == s1  # reuses slot 1
    assert sp.get_record(s_new) == b"D" * 1100
    assert sp.get_record(s0) == b"A" * 1500
    assert sp.get_record(s2) == b"C" * 800


# ============================================================================
# Corruption Detection Tests
# ============================================================================


def test_corruption_invalid_magic() -> None:
    """Verify invalid magic number raises SlottedPageCorruptionError."""
    sp = SlottedPage()
    raw = bytearray(sp.to_bytes())
    # Corrupt magic number at offset 0
    struct.pack_into(">H", raw, 0, 0x1234)

    with pytest.raises(SlottedPageCorruptionError) as exc_info:
        SlottedPage(raw)
    assert "Invalid slotted page magic" in str(exc_info.value)


def test_corruption_header_boundary_violation() -> None:
    """Verify invalid free_space_offset smaller than slot directory raises corruption error."""
    sp = SlottedPage()
    sp.insert_record(b"Record 1")
    raw = bytearray(sp.to_bytes())

    # Set free_space_offset to 4 (smaller than header size of 8)
    struct.pack_into(">H", raw, 6, 4)

    with pytest.raises(SlottedPageCorruptionError) as exc_info:
        SlottedPage(raw)
    assert "Corrupt page boundaries" in str(exc_info.value)


def test_corruption_out_of_bounds_slot_offset() -> None:
    """Verify a slot offset pointing beyond PAGE_SIZE raises corruption error."""
    sp = SlottedPage()
    sp.insert_record(b"Test Record")
    raw = bytearray(sp.to_bytes())

    # Corrupt slot 0 offset to 5000 (> 4096)
    struct.pack_into(">H", raw, PAGE_HEADER_SIZE, 5000)

    with pytest.raises(SlottedPageCorruptionError) as exc_info:
        SlottedPage(raw)
    assert "points out of bounds" in str(exc_info.value)


def test_corruption_overlapping_records() -> None:
    """Verify overlapping records among live slots raise corruption error."""
    sp = SlottedPage()
    sp.insert_record(b"Record 1 (20 bytes)")
    sp.insert_record(b"Record 2 (20 bytes)")
    raw = bytearray(sp.to_bytes())

    # Slot 0 is at offset PAGE_SIZE - 20 (4076)
    # Slot 1 is at offset PAGE_SIZE - 40 (4056)
    # Manually adjust slot 1 offset to 4065, causing it to overlap with slot 0 (4076)
    struct.pack_into(">H", raw, PAGE_HEADER_SIZE + SLOT_ENTRY_SIZE, 4065)

    with pytest.raises(SlottedPageCorruptionError) as exc_info:
        SlottedPage(raw)
    assert "Overlapping records detected" in str(exc_info.value)


# ============================================================================
# PageFile Persistence Integration Tests
# ============================================================================


def test_slotted_page_persistence_with_page_file(tmp_path: Path) -> None:
    """Verify SlottedPage integrates seamlessly with PageFile across write, close, and reopen."""
    db_file = tmp_path / "records.db"

    # 1. Open PageFile, allocate page 0, write records, and persist
    with PageFile(db_file) as pf:
        pid = pf.allocate_page()
        assert pid == PageId(0)

        sp = SlottedPage(page_id=pid)
        r0 = sp.insert_record(b"First Record on Disk")
        r1 = sp.insert_record(b"Second Record on Disk - Longer Payload!")
        r2 = sp.insert_record(b"Third Record")

        # Persist to disk via PageFile
        pf.write_page(pid, sp.to_page())

    # 2. Reopen PageFile in a completely new instance
    with PageFile(db_file) as pf_reopened:
        assert pf_reopened.page_count == 1
        page_from_disk = pf_reopened.read_page(0)

        # Parse back into SlottedPage
        sp_recovered = SlottedPage.from_page(page_from_disk, page_id=0)
        assert sp_recovered.slot_count == 3
        assert sp_recovered.live_record_count == 3
        assert sp_recovered.get_record(r0) == b"First Record on Disk"
        assert sp_recovered.get_record(r1) == b"Second Record on Disk - Longer Payload!"
        assert sp_recovered.get_record(r2) == b"Third Record"

        # Modify page: delete record 1, insert record 3, compact, and write back
        sp_recovered.delete_record(r1)
        r3 = sp_recovered.insert_record(b"Fourth Record replacing Second")
        assert r3 == r1  # slot reuse
        sp_recovered.compact()
        pf_reopened.write_page(0, sp_recovered.to_page())

    # 3. Reopen again to confirm second round of modifications persisted
    with PageFile(db_file) as pf_reopened_again:
        final_page = pf_reopened_again.read_page(0)
        final_sp = SlottedPage.from_page(final_page, page_id=0)
        assert final_sp.live_record_count == 3
        assert final_sp.get_record(r0) == b"First Record on Disk"
        assert final_sp.get_record(r3) == b"Fourth Record replacing Second"
        assert final_sp.get_record(r2) == b"Third Record"


# ============================================================================
# Focused Regression Tests (Refinements & Boundary Conditions)
# ============================================================================


def test_record_id_strict_immutability() -> None:
    """Verify RecordId enforces strict runtime immutability."""
    rid = RecordId(1, 2)
    with pytest.raises(AttributeError) as exc1:
        rid.slot_id = 99  # type: ignore[misc]
    assert "RecordId is immutable" in str(exc1.value)

    with pytest.raises(AttributeError) as exc2:
        rid.page_id = PageId(5)  # type: ignore[misc]
    assert "RecordId is immutable" in str(exc2.value)

    with pytest.raises(AttributeError) as exc3:
        del rid.slot_id  # type: ignore[misc]
    assert "RecordId is immutable" in str(exc3.value)


def test_empty_record_roundtrip() -> None:
    """Verify empty record roundtrips through to_bytes() and from_page()."""
    sp1 = SlottedPage(page_id=0)
    slot_id = sp1.insert_record(b"")
    assert slot_id == 0
    assert sp1.live_record_count == 1
    assert sp1.get_record(slot_id) == b""

    # Roundtrip via raw Page bytes
    raw_page = sp1.to_page()
    sp2 = SlottedPage.from_page(raw_page, page_id=0)
    assert sp2.slot_count == 1
    assert sp2.live_record_count == 1
    assert sp2.get_record(0) == b""


def test_empty_record_after_compaction() -> None:
    """Verify live empty records preserve slot ID and return b'' after compaction."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"A" * 100)
    s1 = sp.insert_record(b"")  # empty record in slot 1
    s2 = sp.insert_record(b"B" * 100)

    # Delete slot 0 to create dead space
    sp.delete_record(s0)

    # Trigger compaction
    sp.compact()

    # Slot 1 should remain the empty record
    assert sp.get_record(s1) == b""
    assert sp.get_record(s2) == b"B" * 100
    with pytest.raises(RecordNotFoundError):
        sp.get_record(s0)


def test_empty_record_deletion() -> None:
    """Verify deleting an empty record invalidates the slot correctly."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"")
    assert sp.live_record_count == 1

    sp.delete_record(s0)
    assert sp.live_record_count == 0

    with pytest.raises(RecordNotFoundError):
        sp.get_record(s0)


def test_empty_slot_reuse_with_empty_and_non_empty() -> None:
    """Verify deleted slot can be reused by an empty record or non-empty record."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"Initial 0")
    s1 = sp.insert_record(b"Initial 1")

    # Delete s0 and reuse with empty record
    sp.delete_record(s0)
    reused_s0 = sp.insert_record(b"")
    assert reused_s0 == s0
    assert sp.get_record(s0) == b""

    # Delete s1 and reuse with non-empty record
    sp.delete_record(s1)
    reused_s1 = sp.insert_record(b"Reused with text")
    assert reused_s1 == s1
    assert sp.get_record(s1) == b"Reused with text"


def test_exact_fit_insertion() -> None:
    """Verify inserting a record of exact maximum capacity (4084 bytes) fills page completely."""
    sp = SlottedPage()
    assert sp.contiguous_free_space_bytes == 4088  # 4096 - 8

    # 4084 bytes record + 4 bytes slot directory = 4088 bytes
    slot_id = sp.insert_record(b"M" * 4084)
    assert slot_id == 0
    assert sp.contiguous_free_space_bytes == 0
    assert sp.total_free_space_bytes == 0
    assert sp.get_record(0) == b"M" * 4084

    # Any further insertion, even 0 bytes (which needs 4 bytes for slot entry), must fail
    with pytest.raises(InsufficientSpaceError):
        sp.insert_record(b"")


def test_compaction_with_empty_and_deleted_slots() -> None:
    """Verify compaction correctly handles mixed active non-empty, active empty, and deleted slots."""
    sp = SlottedPage()
    s0 = sp.insert_record(b"Data0")
    s1 = sp.insert_record(b"")  # empty live
    s2 = sp.insert_record(b"Data2")
    s3 = sp.insert_record(b"Data3")
    s4 = sp.insert_record(b"")  # empty live

    sp.delete_record(s0)
    sp.delete_record(s2)

    # Active: s1 (empty), s3 (Data3), s4 (empty). Deleted: s0, s2.
    assert sp.live_record_count == 3
    sp.compact()

    assert sp.live_record_count == 3
    assert sp.slot_count == 5
    with pytest.raises(RecordNotFoundError):
        sp.get_record(s0)
    assert sp.get_record(s1) == b""
    with pytest.raises(RecordNotFoundError):
        sp.get_record(s2)
    assert sp.get_record(s3) == b"Data3"
    assert sp.get_record(s4) == b""


def test_corruption_invalid_live_zero_length_offset() -> None:
    """Verify a slot with length 0 but offset != LIVE_EMPTY_RECORD_OFFSET raises SlottedPageCorruptionError."""
    sp = SlottedPage()
    sp.insert_record(b"Record")
    raw = bytearray(sp.to_bytes())

    # Slot 0 is at offset PAGE_HEADER_SIZE (8). Set offset=2000, length=0
    # (Not 0 which is deleted, and not 4096 which is LIVE_EMPTY_RECORD_OFFSET)
    struct.pack_into(">HH", raw, PAGE_HEADER_SIZE, 2000, 0)

    with pytest.raises(SlottedPageCorruptionError) as exc_info:
        SlottedPage(raw)
    assert "Invalid live zero-length record" in str(exc_info.value)
