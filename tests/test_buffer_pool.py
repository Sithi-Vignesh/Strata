"""Comprehensive test suite for Phase 3: Buffer Pool Management.

Validates:
- ClockReplacer capacity, tracking, second-chance eviction, pin/unpin transitions.
- Frame descriptor properties, setters, dirty tracking, and reset lifecycle.
- BufferPoolManager initialization, parameter validation, and closed-state enforcement.
- Page fetching, caching, reference counting (pin_count), and repeated fetches.
- New page allocation, initial pin count, and dirty state initialization.
- Unpinning with clean/dirty flags, PageNotCachedError, and InvalidPinCountError.
- Fixed pool capacity enforcement and BufferPoolFullError when all frames are pinned.
- Clean-page eviction without unnecessary disk writes.
- Dirty-page eviction ensuring automatic persistence before frame reuse.
- Explicit page flushing (flush_page, flush_all) and automatic flush on close().
- delete_page behavior on pinned, unpinned, and uncached pages.
- End-to-end integration between BufferPoolManager, SlottedPage, and PageFile.
"""

from pathlib import Path
import pytest

from strata_engine.storage import (
    PAGE_SIZE,
    BufferPoolFullError,
    BufferPoolManager,
    ClockReplacer,
    Frame,
    InvalidPageIdError,
    InvalidPinCountError,
    Page,
    PageFile,
    PageId,
    PageNotCachedError,
    PageNotFoundError,
    SlottedPage,
    StorageClosedError,
)


# ============================================================================
# ClockReplacer Tests
# ============================================================================


def test_clock_replacer_init_valid() -> None:
    """Verify valid ClockReplacer initialization and properties."""
    cr = ClockReplacer(5)
    assert cr.capacity == 5
    assert cr.size() == 0
    assert cr.victim() is None
    assert "ClockReplacer(capacity=5" in repr(cr)


@pytest.mark.parametrize("bad_cap", [0, -1, -10])
def test_clock_replacer_init_invalid_capacity_value(bad_cap: int) -> None:
    """Verify non-positive capacity raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        ClockReplacer(bad_cap)
    assert "at least 1" in str(exc_info.value)


@pytest.mark.parametrize("bad_cap", [True, False, 3.5, "5", None])
def test_clock_replacer_init_invalid_capacity_type(bad_cap: object) -> None:
    """Verify non-integer capacity raises TypeError."""
    with pytest.raises(TypeError):
        ClockReplacer(bad_cap)  # type: ignore[arg-type]


def test_clock_replacer_unpin_and_contains() -> None:
    """Verify unpinning frames tracks them in the replacer."""
    cr = ClockReplacer(3)
    assert not cr.contains(0)
    cr.unpin(0)
    assert cr.contains(0)
    assert cr.size() == 1

    cr.unpin(2)
    assert cr.contains(2)
    assert cr.size() == 2


def test_clock_replacer_pin_removes_from_replacer() -> None:
    """Verify pinning an unpinned frame removes it from candidate list."""
    cr = ClockReplacer(3)
    cr.unpin(0)
    cr.unpin(1)
    assert cr.size() == 2

    cr.pin(0)
    assert not cr.contains(0)
    assert cr.size() == 1


def test_clock_replacer_victim_second_chance_cycle() -> None:
    """Verify second-chance clock cycle behavior when evicting."""
    # Capacity 3: frames 0, 1, 2
    cr = ClockReplacer(3)
    cr.unpin(0)
    cr.unpin(1)
    cr.unpin(2)
    assert cr.size() == 3

    # All unpinned frames start with ref_bit = True.
    # On victim(), hand traverses 0 (bit=0), 1 (bit=0), 2 (bit=0), then picks 0!
    victim1 = cr.victim()
    assert victim1 == 0
    assert not cr.contains(0)
    assert cr.size() == 2

    # Clock hand is now at 1. Since ref_bit for 1 and 2 was cleared to 0 in the first pass:
    victim2 = cr.victim()
    assert victim2 == 1
    assert cr.size() == 1

    victim3 = cr.victim()
    assert victim3 == 2
    assert cr.size() == 0

    assert cr.victim() is None


def test_clock_replacer_re_unpin_refreshes_ref_bit() -> None:
    """Verify re-unpinning an existing candidate frame resets its reference bit."""
    cr = ClockReplacer(2)
    cr.unpin(0)
    cr.unpin(1)

    # Frame 0 and 1 have ref_bit = True.
    # First victim(): 0's bit cleared, 1's bit cleared, 0 picked.
    assert cr.victim() == 0

    # 1 now has ref_bit = False. If we unpin(1) again, its ref_bit should be True again.
    cr.unpin(1)
    cr.unpin(0)

    # Hand was at 1. 1 has ref_bit=True, 0 has ref_bit=True.
    # 1's bit cleared, 0's bit cleared, 1 picked.
    assert cr.victim() == 1


@pytest.mark.parametrize("bad_fid", [-1, 3, 4])
def test_clock_replacer_bounds_checking(bad_fid: int) -> None:
    """Verify invalid frame IDs raise ValueError."""
    cr = ClockReplacer(3)
    with pytest.raises(ValueError):
        cr.unpin(bad_fid)
    with pytest.raises(ValueError):
        cr.pin(bad_fid)
    with pytest.raises(ValueError):
        cr.contains(bad_fid)


# ============================================================================
# Frame Tests
# ============================================================================


def test_frame_initial_state() -> None:
    """Verify Frame initializes in empty, unpinned, clean state."""
    f = Frame(0)
    assert f.frame_id == 0
    assert f.page_id is None
    assert f.page is None
    assert f.pin_count == 0
    assert not f.is_dirty
    assert not f.is_pinned
    assert f.is_empty
    assert "status=empty" in repr(f)


def test_frame_mutation_and_reset() -> None:
    """Verify mutating frame state and resetting it."""
    f = Frame(1)
    p = Page.blank()
    pid = PageId(4)

    f.page_id = pid
    f.page = p
    f.pin_count = 2
    f.is_dirty = True

    assert not f.is_empty
    assert f.is_pinned
    assert f.pin_count == 2
    assert f.is_dirty
    assert f.page_id == pid
    assert f.page == p
    assert "dirty=True" in repr(f)

    f.reset()
    assert f.is_empty
    assert not f.is_pinned
    assert f.pin_count == 0
    assert not f.is_dirty
    assert f.page_id is None
    assert f.page is None


# ============================================================================
# BufferPoolManager Lifecycle & Parameter Validation
# ============================================================================


def test_buffer_pool_manager_init_valid(tmp_path: Path) -> None:
    """Verify valid BufferPoolManager initialization."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=5)
        assert bpm.pool_size == 5
        assert bpm.cached_page_count == 0
        assert not bpm.is_closed
        assert bpm.page_file is pf
        assert "cached=0/5" in repr(bpm)


def test_buffer_pool_manager_init_closed_page_file(tmp_path: Path) -> None:
    """Verify initializing BufferPoolManager with a closed PageFile raises StorageClosedError."""
    db_file = tmp_path / "test.db"
    pf = PageFile(db_file)
    pf.close()

    with pytest.raises(StorageClosedError):
        BufferPoolManager(pf, pool_size=5)


@pytest.mark.parametrize("bad_size", [0, -1, -5])
def test_buffer_pool_manager_init_invalid_size_value(tmp_path: Path, bad_size: int) -> None:
    """Verify non-positive pool_size raises ValueError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        with pytest.raises(ValueError):
            BufferPoolManager(pf, pool_size=bad_size)


@pytest.mark.parametrize("bad_size", [True, False, 2.5, "10", None])
def test_buffer_pool_manager_init_invalid_size_type(tmp_path: Path, bad_size: object) -> None:
    """Verify non-integer pool_size raises TypeError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        with pytest.raises(TypeError):
            BufferPoolManager(pf, pool_size=bad_size)  # type: ignore[arg-type]


def test_buffer_pool_manager_operations_after_close(tmp_path: Path) -> None:
    """Verify operations raise StorageClosedError once closed."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)
        bpm.close()
        assert bpm.is_closed

        with pytest.raises(StorageClosedError):
            bpm.fetch_page(0)
        with pytest.raises(StorageClosedError):
            bpm.new_page()
        with pytest.raises(StorageClosedError):
            bpm.unpin_page(0)
        with pytest.raises(StorageClosedError):
            bpm.flush_page(0)
        with pytest.raises(StorageClosedError):
            bpm.flush_all()


# ============================================================================
# Page Fetching and Caching Tests
# ============================================================================


def test_fetch_page_existing(tmp_path: Path) -> None:
    """Verify fetching an existing page from disk into buffer pool."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pid = pf.allocate_page()
        test_page = Page(b"\x42" * PAGE_SIZE)
        pf.write_page(pid, test_page)

        bpm = BufferPoolManager(pf, pool_size=3)
        assert not bpm.contains_page(pid)

        fetched = bpm.fetch_page(pid)
        assert fetched == test_page
        assert bpm.contains_page(pid)
        assert bpm.cached_page_count == 1
        assert bpm.get_pin_count(pid) == 1
        assert not bpm.is_dirty(pid)


def test_fetch_page_repeated_returns_same_instance_and_increments_pin(tmp_path: Path) -> None:
    """Verify repeated fetch of same page returns identical Page instance and increments pin count."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pid = pf.allocate_page()
        bpm = BufferPoolManager(pf, pool_size=3)

        p1 = bpm.fetch_page(pid)
        assert bpm.get_pin_count(pid) == 1

        p2 = bpm.fetch_page(pid)
        assert bpm.get_pin_count(pid) == 2
        assert p1 is p2  # Same in-memory instance
        assert bpm.cached_page_count == 1


def test_fetch_page_not_found(tmp_path: Path) -> None:
    """Verify fetching unallocated page raises PageNotFoundError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        with pytest.raises(PageNotFoundError):
            bpm.fetch_page(999)


@pytest.mark.parametrize("bad_pid", [-1, True, "0", 2.0])
def test_fetch_page_invalid_page_id(tmp_path: Path, bad_pid: object) -> None:
    """Verify invalid PageId types and values raise InvalidPageIdError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        with pytest.raises(InvalidPageIdError):
            bpm.fetch_page(bad_pid)  # type: ignore[arg-type]


# ============================================================================
# New Page Allocation Tests
# ============================================================================


def test_new_page_allocation(tmp_path: Path) -> None:
    """Verify new_page creates a blank pinned page marked dirty."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)

        pid, page = bpm.new_page()
        assert pid == PageId(0)
        assert len(page) == PAGE_SIZE
        assert page == Page.blank()
        assert bpm.cached_page_count == 1
        assert bpm.get_pin_count(pid) == 1
        assert bpm.is_dirty(pid)

        # Successive allocation
        pid2, page2 = bpm.new_page()
        assert pid2 == PageId(1)
        assert bpm.cached_page_count == 2
        assert bpm.get_pin_count(pid2) == 1


# ============================================================================
# Unpinning Tests
# ============================================================================


def test_unpin_page_decrements_pin_count(tmp_path: Path) -> None:
    """Verify unpinning decrements pin count."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        pid, _ = bpm.new_page()
        assert bpm.get_pin_count(pid) == 1

        bpm.unpin_page(pid)
        assert bpm.get_pin_count(pid) == 0


def test_unpin_page_with_dirty_flag(tmp_path: Path) -> None:
    """Verify unpinning with is_dirty=True sets dirty flag."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        pid = pf.allocate_page()
        bpm = BufferPoolManager(pf, pool_size=3)

        bpm.fetch_page(pid)
        assert not bpm.is_dirty(pid)

        bpm.unpin_page(pid, is_dirty=True)
        assert bpm.is_dirty(pid)


def test_unpin_page_preserves_dirty_if_unpinned_clean(tmp_path: Path) -> None:
    """Verify unpinning with is_dirty=False does not erase existing dirty status."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        pid, _ = bpm.new_page()  # initially dirty
        assert bpm.is_dirty(pid)

        bpm.fetch_page(pid)  # pin count = 2
        bpm.unpin_page(pid, is_dirty=False)
        assert bpm.is_dirty(pid)  # Remains dirty


def test_unpin_page_not_cached_raises(tmp_path: Path) -> None:
    """Verify unpinning non-cached page raises PageNotCachedError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        with pytest.raises(PageNotCachedError):
            bpm.unpin_page(0)


def test_unpin_page_zero_pin_count_raises(tmp_path: Path) -> None:
    """Verify unpinning a page whose pin_count is already 0 raises InvalidPinCountError."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        pid, _ = bpm.new_page()
        bpm.unpin_page(pid)
        assert bpm.get_pin_count(pid) == 0

        with pytest.raises(InvalidPinCountError):
            bpm.unpin_page(pid)


# ============================================================================
# Eviction and Capacity Enforcement Tests
# ============================================================================


def test_buffer_pool_full_when_all_pinned(tmp_path: Path) -> None:
    """Verify BufferPoolFullError is raised when capacity is exhausted and all frames are pinned."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)
        bpm.new_page()
        bpm.new_page()
        assert bpm.cached_page_count == 2

        # Both frames are pinned (pin_count = 1). Next new_page must fail!
        with pytest.raises(BufferPoolFullError) as exc_info:
            bpm.new_page()
        assert "all 2 frames are currently pinned" in str(exc_info.value)


def test_clean_page_eviction(tmp_path: Path) -> None:
    """Verify unpinned clean page is evicted to make room for a new page without error."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        p0 = pf.allocate_page()
        p1 = pf.allocate_page()
        p2 = pf.allocate_page()

        bpm = BufferPoolManager(pf, pool_size=2)
        bpm.fetch_page(p0)
        bpm.fetch_page(p1)
        assert bpm.cached_page_count == 2

        # Unpin p0 (clean). p1 remains pinned.
        bpm.unpin_page(p0, is_dirty=False)

        # Fetching p2 should evict p0 (the only unpinned frame)
        bpm.fetch_page(p2)
        assert bpm.cached_page_count == 2
        assert not bpm.contains_page(p0)
        assert bpm.contains_page(p1)
        assert bpm.contains_page(p2)


def test_dirty_page_eviction_persists_data(tmp_path: Path) -> None:
    """Verify that when an unpinned dirty page is evicted, its data is safely persisted to disk."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)

        # Allocate page 0 and write distinctive bytes
        pid0, page0 = bpm.new_page()
        page0._data[0:4] = b"TEST"
        bpm.unpin_page(pid0, is_dirty=True)

        # Allocate page 1 and unpin
        pid1, _ = bpm.new_page()
        bpm.unpin_page(pid1, is_dirty=False)

        # Buffer pool has 2 pages, both unpinned.
        # Now allocate page 2: will evict one frame (page 0 or 1).
        pid2, _ = bpm.new_page()
        bpm.unpin_page(pid2, is_dirty=False)

        # Allocate page 3: will evict the remaining first frame.
        pid3, _ = bpm.new_page()
        bpm.unpin_page(pid3, is_dirty=False)

        # Page 0 has definitely been evicted from buffer pool
        assert not bpm.contains_page(pid0)

    # Reopen PageFile and read page 0 directly from disk
    with PageFile(db_file) as pf_reopened:
        disk_page = pf_reopened.read_page(pid0)
        assert disk_page._data[0:4] == b"TEST"


# ============================================================================
# Flushing Tests
# ============================================================================


def test_flush_page(tmp_path: Path) -> None:
    """Verify flush_page writes dirty data to disk and clears dirty flag."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)
        pid, page = bpm.new_page()
        page._data[0:4] = b"SYNC"
        assert bpm.is_dirty(pid)

        bpm.flush_page(pid)
        assert not bpm.is_dirty(pid)

        # Check disk contents immediately
        disk_page = pf.read_page(pid)
        assert disk_page._data[0:4] == b"SYNC"


def test_flush_all(tmp_path: Path) -> None:
    """Verify flush_all writes all dirty pages and clears their dirty flags."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=3)
        pid0, page0 = bpm.new_page()
        pid1, page1 = bpm.new_page()
        page0._data[0:4] = b"AAA0"
        page1._data[0:4] = b"BBB1"

        assert bpm.is_dirty(pid0)
        assert bpm.is_dirty(pid1)

        bpm.flush_all()
        assert not bpm.is_dirty(pid0)
        assert not bpm.is_dirty(pid1)

        assert pf.read_page(pid0)._data[0:4] == b"AAA0"
        assert pf.read_page(pid1)._data[0:4] == b"BBB1"


def test_close_flushes_automatically(tmp_path: Path) -> None:
    """Verify closing BufferPoolManager automatically flushes dirty pages."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)
        pid, page = bpm.new_page()
        page._data[0:4] = b"EXIT"
        bpm.close()

        assert pf.read_page(pid)._data[0:4] == b"EXIT"


def test_context_manager_usage(tmp_path: Path) -> None:
    """Verify context manager automatically flushes and closes."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        with BufferPoolManager(pf, pool_size=2) as bpm:
            pid, page = bpm.new_page()
            page._data[0:4] = b"WITH"
        assert bpm.is_closed
        assert pf.read_page(pid)._data[0:4] == b"WITH"


# ============================================================================
# delete_page Tests
# ============================================================================


def test_delete_page_behavior(tmp_path: Path) -> None:
    """Verify delete_page clears unpinned cached page and rejects pinned page."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)
        pid0, _ = bpm.new_page()

        # Cannot delete while pinned
        assert not bpm.delete_page(pid0)
        assert bpm.contains_page(pid0)

        # Unpin and delete
        bpm.unpin_page(pid0)
        assert bpm.delete_page(pid0)
        assert not bpm.contains_page(pid0)
        assert bpm.cached_page_count == 0

        # Deleting non-cached page returns True
        assert bpm.delete_page(999)


# ============================================================================
# End-to-End Integration with SlottedPage
# ============================================================================


def test_integration_slotted_page_with_buffer_pool(tmp_path: Path) -> None:
    """Verify end-to-end integration of SlottedPage within BufferPoolManager."""
    db_file = tmp_path / "test.db"
    with PageFile(db_file) as pf:
        bpm = BufferPoolManager(pf, pool_size=2)

        # 1. Allocate a page through BufferPoolManager
        pid, page = bpm.new_page()

        # 2. Initialize a SlottedPage and insert records
        sp = SlottedPage(page_id=pid)
        slot0 = sp.insert_record(b"Task: Implement Buffer Manager")
        slot1 = sp.insert_record(b"Task: Verify Clock Replacement")
        assert sp.get_record(slot0) == b"Task: Implement Buffer Manager"
        assert sp.get_record(slot1) == b"Task: Verify Clock Replacement"

        # Copy serialized slotted page into buffer frame
        page._data[:] = sp.to_bytes()

        # Unpin page as dirty
        bpm.unpin_page(pid, is_dirty=True)

        # 3. Force eviction by allocating two more pages
        p1, _ = bpm.new_page()
        bpm.unpin_page(p1, is_dirty=False)
        p2, _ = bpm.new_page()
        bpm.unpin_page(p2, is_dirty=False)

        # Ensure page 0 was evicted
        assert not bpm.contains_page(pid)

        # 4. Fetch page 0 again from disk via buffer manager
        refetched_page = bpm.fetch_page(pid)
        recovered_sp = SlottedPage.from_page(refetched_page, page_id=pid)

        assert recovered_sp.get_record(slot0) == b"Task: Implement Buffer Manager"
        assert recovered_sp.get_record(slot1) == b"Task: Verify Clock Replacement"

        bpm.unpin_page(pid, is_dirty=False)
