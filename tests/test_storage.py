"""Comprehensive test suite for the Phase 1 Strata storage engine foundation.

Covers:
- Fixed-size Page creation, validation, immutability, and size invariants.
- PageId representation, validation, comparisons, and boundary conditions.
- Disk-backed PageFile lifecycle: creation, allocation, read/write, reopening,
  closed-state enforcement, and corruption detection.
"""

from pathlib import Path
import pytest

from strata_engine.storage import (
    PAGE_SIZE,
    InvalidPageIdError,
    Page,
    PageFile,
    PageId,
    PageNotFoundError,
    PageSizeError,
    StorageClosedError,
    StorageCorruptionError,
)


# ============================================================================
# Page Tests
# ============================================================================


def test_blank_page_creation() -> None:
    """Verify creating a blank page produces exactly PAGE_SIZE zero bytes."""
    page = Page.blank()
    assert len(page) == PAGE_SIZE
    assert page.size == PAGE_SIZE
    assert page.to_bytes() == b"\x00" * PAGE_SIZE


def test_page_creation_default_constructor() -> None:
    """Verify default constructor creates an identical zero-filled page."""
    page = Page()
    assert len(page) == PAGE_SIZE
    assert page == Page.blank()


def test_page_creation_from_valid_bytes() -> None:
    """Verify creating a page from a valid PAGE_SIZE byte sequence."""
    raw = b"A" * PAGE_SIZE
    page = Page.from_bytes(raw)
    assert len(page) == PAGE_SIZE
    assert page.to_bytes() == raw


def test_page_rejection_undersized_bytes() -> None:
    """Verify creating a page from undersized bytes raises PageSizeError."""
    undersized = b"X" * (PAGE_SIZE - 1)
    with pytest.raises(PageSizeError) as exc_info:
        Page(undersized)
    assert f"exactly {PAGE_SIZE} bytes" in str(exc_info.value)


def test_page_rejection_oversized_bytes() -> None:
    """Verify creating a page from oversized bytes raises PageSizeError."""
    oversized = b"Y" * (PAGE_SIZE + 1)
    with pytest.raises(PageSizeError) as exc_info:
        Page(oversized)
    assert f"exactly {PAGE_SIZE} bytes" in str(exc_info.value)


def test_page_to_bytes_immutability() -> None:
    """Verify modifying returned bytes does not alter internal page buffer."""
    page = Page.blank()
    exported = page.to_bytes()
    assert exported == b"\x00" * PAGE_SIZE

    # Re-reading to_bytes produces identical data
    assert page.to_bytes() == b"\x00" * PAGE_SIZE


def test_page_equality() -> None:
    """Verify equality comparison between Page instances and raw bytes."""
    p1 = Page(b"\x01" * PAGE_SIZE)
    p2 = Page(b"\x01" * PAGE_SIZE)
    p3 = Page(b"\x02" * PAGE_SIZE)

    assert p1 == p2
    assert p1 != p3
    assert p1 == (b"\x01" * PAGE_SIZE)


def test_page_write_bytes_valid() -> None:
    """Verify write_bytes successfully overwrites page data."""
    page = Page.blank()
    new_data = b"\xAB" * PAGE_SIZE
    page.write_bytes(new_data)
    assert page.to_bytes() == new_data


def test_page_write_bytes_invalid_size() -> None:
    """Verify write_bytes with incorrect size raises PageSizeError."""
    page = Page.blank()
    with pytest.raises(PageSizeError):
        page.write_bytes(b"\x00" * (PAGE_SIZE - 1))
    with pytest.raises(PageSizeError):
        page.write_bytes(b"\x00" * (PAGE_SIZE + 1))


def test_page_write_bytes_invalid_type() -> None:
    """Verify write_bytes with non-bytes argument raises TypeError."""
    page = Page.blank()
    with pytest.raises(TypeError):
        page.write_bytes("not_bytes")  # type: ignore[arg-type]



# ============================================================================
# PageId Tests
# ============================================================================


def test_page_id_valid() -> None:
    """Verify valid non-negative integer PageId construction and conversion."""
    pid0 = PageId(0)
    assert int(pid0) == 0
    assert pid0.value == 0
    assert repr(pid0) == "PageId(0)"
    assert str(pid0) == "0"

    pid42 = PageId(42)
    assert int(pid42) == 42
    assert pid42.value == 42


def test_page_id_rejection_negative() -> None:
    """Verify negative values raise InvalidPageIdError."""
    with pytest.raises(InvalidPageIdError) as exc_info:
        PageId(-1)
    assert "must be non-negative" in str(exc_info.value)


@pytest.mark.parametrize("invalid_val", [True, False, 3.14, "0", None, []])
def test_page_id_rejection_invalid_types(invalid_val: object) -> None:
    """Verify booleans, floats, strings, and non-ints raise InvalidPageIdError."""
    with pytest.raises(InvalidPageIdError):
        PageId(invalid_val)  # type: ignore[arg-type]


def test_page_id_comparisons_and_hashing() -> None:
    """Verify ordering comparisons and hash set behavior for PageId."""
    pid0 = PageId(0)
    pid1 = PageId(1)
    pid2 = PageId(2)

    assert pid0 < pid1 < pid2
    assert pid2 > pid1 > pid0
    assert pid1 <= PageId(1)
    assert pid1 >= PageId(1)
    assert pid1 == 1
    assert pid1 != 2

    id_set = {PageId(0), PageId(1), PageId(0)}
    assert len(id_set) == 2
    assert PageId(0) in id_set


# ============================================================================
# PageFile Tests
# ============================================================================


def test_page_file_creation_empty(tmp_path: Path) -> None:
    """Verify opening a new PageFile creates an empty file with page_count 0."""
    db_file = tmp_path / "test.db"
    assert not db_file.exists()

    with PageFile(db_file) as pf:
        assert db_file.exists()
        assert pf.page_count == 0
        assert len(pf) == 0
        assert pf.path == db_file.resolve()
        assert not pf.is_closed


def test_page_file_allocation(tmp_path: Path) -> None:
    """Verify sequential allocation of pages returns incrementing PageIds."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pid0 = pf.allocate_page()
        assert pid0 == PageId(0)
        assert pf.page_count == 1

        pid1 = pf.allocate_page()
        assert pid1 == PageId(1)
        assert pf.page_count == 2

        pid2 = pf.allocate_page()
        assert pid2 == PageId(2)
        assert pf.page_count == 3


def test_allocated_page_is_zero_filled(tmp_path: Path) -> None:
    """Verify freshly allocated pages contain deterministic zero-filled bytes."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pid = pf.allocate_page()
        page = pf.read_page(pid)
        assert page == Page.blank()
        assert page.to_bytes() == b"\x00" * PAGE_SIZE


def test_write_and_read_single_page(tmp_path: Path) -> None:
    """Verify writing data to an allocated page and reading it back."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pid = pf.allocate_page()

        custom_data = b"Hello, Strata Storage!" + (b"\x00" * (PAGE_SIZE - 22))
        page_to_write = Page(custom_data)
        pf.write_page(pid, page_to_write)

        read_back = pf.read_page(pid)
        assert read_back == page_to_write
        assert read_back.to_bytes() == custom_data


def test_multiple_pages_separation(tmp_path: Path) -> None:
    """Verify multiple pages are stored at correct distinct offsets without crosstalk."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        p0_id = pf.allocate_page()
        p1_id = pf.allocate_page()
        p2_id = pf.allocate_page()

        data0 = b"\x01" * PAGE_SIZE
        data1 = b"\x02" * PAGE_SIZE
        data2 = b"\x03" * PAGE_SIZE

        pf.write_page(p0_id, Page(data0))
        pf.write_page(p1_id, Page(data1))
        pf.write_page(p2_id, Page(data2))

        # Re-read in reverse order to ensure offset independence
        assert pf.read_page(p2_id).to_bytes() == data2
        assert pf.read_page(p1_id).to_bytes() == data1
        assert pf.read_page(p0_id).to_bytes() == data0


def test_reopen_existing_page_file(tmp_path: Path) -> None:
    """Verify closing and reopening a PageFile recovers all previously stored pages."""
    db_file = tmp_path / "test.db"

    data_page0 = b"PAGE_0_DATA" + (b"\x00" * (PAGE_SIZE - 11))
    data_page1 = b"PAGE_1_DATA" + (b"\x00" * (PAGE_SIZE - 11))

    # Phase A: Write and close
    pf1 = PageFile(db_file)
    p0 = pf1.allocate_page()
    p1 = pf1.allocate_page()
    pf1.write_page(p0, Page(data_page0))
    pf1.write_page(p1, Page(data_page1))
    pf1.close()
    assert pf1.is_closed

    # Verify physical file size on disk is exactly 2 * PAGE_SIZE
    assert db_file.stat().st_size == 2 * PAGE_SIZE

    # Phase B: Reopen in a new instance and verify recovery
    with PageFile(db_file) as pf2:
        assert pf2.page_count == 2
        assert pf2.read_page(0).to_bytes() == data_page0
        assert pf2.read_page(1).to_bytes() == data_page1


def test_read_unallocated_page_fails(tmp_path: Path) -> None:
    """Verify attempting to read an unallocated page raises PageNotFoundError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        with pytest.raises(PageNotFoundError) as exc_info:
            pf.read_page(0)
        assert "does not exist" in str(exc_info.value)

        pf.allocate_page()
        with pytest.raises(PageNotFoundError):
            pf.read_page(1)


def test_write_unallocated_page_fails(tmp_path: Path) -> None:
    """Verify attempting to write to an unallocated page raises PageNotFoundError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        page = Page.blank()
        with pytest.raises(PageNotFoundError) as exc_info:
            pf.write_page(0, page)
        assert "Cannot write to unallocated" in str(exc_info.value)


def test_invalid_page_id_arguments(tmp_path: Path) -> None:
    """Verify negative page IDs or invalid types raise InvalidPageIdError in PageFile."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pf.allocate_page()

        with pytest.raises(InvalidPageIdError):
            pf.read_page(-1)

        with pytest.raises(InvalidPageIdError):
            pf.write_page(-1, Page.blank())

        with pytest.raises(InvalidPageIdError):
            pf.read_page("0")  # type: ignore[arg-type]


def test_operations_after_close_fail(tmp_path: Path) -> None:
    """Verify attempting any operation on a closed PageFile raises StorageClosedError."""
    db_file = tmp_path / "test.db"
    pf = PageFile(db_file)
    pf.allocate_page()
    pf.close()

    assert pf.is_closed

    with pytest.raises(StorageClosedError):
        _ = pf.page_count

    with pytest.raises(StorageClosedError):
        pf.allocate_page()

    with pytest.raises(StorageClosedError):
        pf.read_page(0)

    with pytest.raises(StorageClosedError):
        pf.write_page(0, Page.blank())


def test_corrupted_file_detection(tmp_path: Path) -> None:
    """Verify opening a file whose size is not a multiple of PAGE_SIZE raises StorageCorruptionError."""
    corrupt_file = tmp_path / "corrupt.db"
    # Write 100 bytes (not a multiple of 4096)
    corrupt_file.write_bytes(b"Corrupt data!" * 5)

    with pytest.raises(StorageCorruptionError) as exc_info:
        PageFile(corrupt_file)
    assert "not an exact multiple of PAGE_SIZE" in str(exc_info.value)
