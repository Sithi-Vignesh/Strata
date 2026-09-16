"""Buffer pool manager and frame abstraction.

Provides the BufferPoolManager class and Frame descriptor to mediate all
page requests between higher-level storage access methods and disk-backed PageFiles.
Enforces fixed-capacity frame management, pin/unpin reference counting,
dirty page tracking, and CLOCK eviction.
"""

from typing import Any, Dict, List, Optional, Tuple, Union

from strata_engine.storage.exceptions import (
    BufferPoolFullError,
    InvalidPageIdError,
    InvalidPinCountError,
    PageNotCachedError,
    PageNotFoundError,
    StorageClosedError,
)
from strata_engine.storage.page import Page
from strata_engine.storage.page_file import PageFile
from strata_engine.storage.page_id import PageId, validate_page_id
from strata_engine.storage.replacer import ClockReplacer, Replacer


class Frame:
    """Represents a discrete in-memory slot in the buffer pool."""

    __slots__ = ("_frame_id", "_page_id", "_page", "_pin_count", "_is_dirty")

    def __init__(self, frame_id: int) -> None:
        """Initialize an empty Frame.

        Args:
            frame_id: Integer index representing the frame's position in the pool.
        """
        self._frame_id: int = frame_id
        self._page_id: Optional[PageId] = None
        self._page: Optional[Page] = None
        self._pin_count: int = 0
        self._is_dirty: bool = False

    @property
    def frame_id(self) -> int:
        """Return the index of this frame in the buffer pool."""
        return self._frame_id

    @property
    def page_id(self) -> Optional[PageId]:
        """Return the PageId currently resident in this frame, if any."""
        return self._page_id

    @page_id.setter
    def page_id(self, value: Optional[PageId]) -> None:
        self._page_id = value

    @property
    def page(self) -> Optional[Page]:
        """Return the in-memory Page instance stored in this frame."""
        return self._page

    @page.setter
    def page(self, value: Optional[Page]) -> None:
        self._page = value

    @property
    def pin_count(self) -> int:
        """Return the current reference/pin count for this frame."""
        return self._pin_count

    @pin_count.setter
    def pin_count(self, value: int) -> None:
        self._pin_count = value

    @property
    def is_dirty(self) -> bool:
        """Return whether this frame's page has unwritten modifications."""
        return self._is_dirty

    @is_dirty.setter
    def is_dirty(self, value: bool) -> None:
        self._is_dirty = value

    @property
    def is_pinned(self) -> bool:
        """Return True if this frame is currently pinned (pin_count > 0)."""
        return self._pin_count > 0

    @property
    def is_empty(self) -> bool:
        """Return True if this frame does not currently hold a page."""
        return self._page_id is None

    def reset(self) -> None:
        """Reset the frame to an empty, unpinned, clean state."""
        self._page_id = None
        self._page = None
        self._pin_count = 0
        self._is_dirty = False

    def __repr__(self) -> str:
        if self.is_empty:
            return f"Frame(id={self._frame_id}, status=empty)"
        return (
            f"Frame(id={self._frame_id}, page_id={self._page_id}, "
            f"pin_count={self._pin_count}, dirty={self._is_dirty})"
        )


class BufferPoolManager:
    """Manages an in-memory pool of fixed-size Page frames.

    Mediates all page operations between higher-level storage engines and the
    disk-backed PageFile. Guarantees that:
    - In-memory pages never exceed the configured pool capacity.
    - Pinned pages are protected from eviction.
    - Dirty pages are safely written to disk before frame eviction or during flush.
    - Eviction follows the deterministic CLOCK (Second-Chance) replacement policy.
    """

    def __init__(self, page_file: PageFile, pool_size: int = 10) -> None:
        """Initialize the BufferPoolManager.

        Args:
            page_file: Disk-backed PageFile instance for underlying I/O.
            pool_size: Maximum number of frames in the buffer pool (default 10).

        Raises:
            TypeError: If page_file is not a PageFile or pool_size is not an int.
            ValueError: If pool_size < 1.
            StorageClosedError: If page_file is closed.
        """
        if not isinstance(page_file, PageFile):
            raise TypeError(f"Expected PageFile instance, got {type(page_file).__name__}.")
        if page_file.is_closed:
            raise StorageClosedError(f"Cannot initialize BufferPoolManager on closed PageFile: '{page_file.path}'.")

        if isinstance(pool_size, bool) or not isinstance(pool_size, int):
            raise TypeError(f"pool_size must be an integer, got {type(pool_size).__name__}.")
        if pool_size < 1:
            raise ValueError(f"pool_size must be at least 1, got {pool_size}.")

        self._page_file: PageFile = page_file
        self._pool_size: int = pool_size
        self._frames: List[Frame] = [Frame(i) for i in range(pool_size)]
        self._page_table: Dict[PageId, int] = {}
        self._replacer: Replacer = ClockReplacer(pool_size)
        self._free_list: List[int] = list(range(pool_size))
        self._closed: bool = False

    @property
    def pool_size(self) -> int:
        """Return the maximum frame capacity of the buffer pool."""
        return self._pool_size

    @property
    def cached_page_count(self) -> int:
        """Return the number of pages currently cached in memory."""
        return len(self._page_table)

    @property
    def is_closed(self) -> bool:
        """Return whether the buffer pool manager is closed."""
        return self._closed

    @property
    def page_file(self) -> PageFile:
        """Return the underlying PageFile."""
        return self._page_file

    def _check_not_closed(self) -> None:
        """Raise StorageClosedError if operations are attempted after closure."""
        if self._closed or self._page_file.is_closed:
            raise StorageClosedError("Operation attempted on closed BufferPoolManager.")

    def _get_available_frame(self) -> int:
        """Find a frame to host a new or fetched page.

        First checks the free list. If empty, asks the replacer for an
        unpinned victim frame. If a dirty victim is selected, flushes it
        to disk before reassigning the frame.

        Returns:
            int frame_id of the available frame.

        Raises:
            BufferPoolFullError: If all frames in the pool are currently pinned.
        """
        if self._free_list:
            return self._free_list.pop(0)

        victim_fid = self._replacer.victim()
        if victim_fid is None:
            raise BufferPoolFullError(
                f"Buffer pool is full: all {self._pool_size} frames are currently pinned."
            )

        victim_frame = self._frames[victim_fid]

        # If the victim page is dirty, flush its contents to disk before reuse
        if victim_frame.is_dirty and victim_frame.page_id is not None and victim_frame.page is not None:
            self._page_file.write_page(victim_frame.page_id, victim_frame.page)
            victim_frame.is_dirty = False

        # Remove from page lookup table
        if victim_frame.page_id is not None and victim_frame.page_id in self._page_table:
            del self._page_table[victim_frame.page_id]

        victim_frame.reset()
        return victim_fid

    def fetch_page(self, page_id: Union[PageId, int]) -> Page:
        """Fetch a page into memory by its PageId and increment its pin count.

        If the page is already resident in the buffer pool, increments its
        pin count, updates the replacer, and returns the cached Page instance.

        If the page is not in the buffer pool:
        1. Selects an available frame (evicting an unpinned page if necessary).
        2. Reads the page from the underlying PageFile.
        3. Sets pin_count = 1 and marks it clean.
        4. Returns the Page instance.

        Args:
            page_id: PageId or non-negative integer identifying the page.

        Returns:
            Page instance corresponding to page_id.

        Raises:
            StorageClosedError: If the manager or PageFile is closed.
            InvalidPageIdError: If page_id is invalid.
            PageNotFoundError: If page_id does not exist in PageFile.
            BufferPoolFullError: If all frames are pinned and page is not cached.
        """
        self._check_not_closed()
        pid = validate_page_id(page_id)

        # Case 1: Page is already cached in memory
        if pid in self._page_table:
            fid = self._page_table[pid]
            frame = self._frames[fid]
            frame.pin_count += 1
            self._replacer.pin(fid)
            assert frame.page is not None
            return frame.page

        # Case 2: Page is not cached; verify existence on disk before obtaining frame
        current_disk_pages = self._page_file.page_count
        if pid.value >= current_disk_pages:
            raise PageNotFoundError(
                f"PageId {pid.value} does not exist in '{self._page_file.path}'. "
                f"Current allocated pages: {current_disk_pages}."
            )

        # Secure a frame (may evict an unpinned frame)
        fid = self._get_available_frame()
        frame = self._frames[fid]

        # Read page from disk
        disk_page = self._page_file.read_page(pid)

        # Populate frame
        frame.page_id = pid
        frame.page = disk_page
        frame.pin_count = 1
        frame.is_dirty = False

        # Update page table and replacer
        self._page_table[pid] = fid
        self._replacer.pin(fid)

        return disk_page

    def new_page(self) -> Tuple[PageId, Page]:
        """Allocate a new page on disk and load it into a pinned buffer frame.

        Finds an available frame first to ensure memory capacity is available,
        then calls PageFile.allocate_page() and loads a blank Page into the frame.

        Returns:
            Tuple of (new_page_id, page).

        Raises:
            StorageClosedError: If the manager or PageFile is closed.
            BufferPoolFullError: If all frames are currently pinned.
        """
        self._check_not_closed()

        # Find an available frame BEFORE allocating on disk
        fid = self._get_available_frame()
        frame = self._frames[fid]

        # Allocate new page on disk
        new_pid = self._page_file.allocate_page()
        new_page = Page.blank()

        # Populate frame
        frame.page_id = new_pid
        frame.page = new_page
        frame.pin_count = 1
        frame.is_dirty = True  # Newly created page marked dirty to ensure persistence

        # Update page table and replacer
        self._page_table[new_pid] = fid
        self._replacer.pin(fid)

        return new_pid, new_page

    def unpin_page(self, page_id: Union[PageId, int], is_dirty: bool = False) -> None:
        """Decrement the pin count of a page and optionally mark it dirty.

        When pin_count drops to 0, the frame becomes eligible for eviction
        via the replacement policy.

        Args:
            page_id: PageId or non-negative integer identifying the page.
            is_dirty: Set to True if the page contents were modified in memory.

        Raises:
            StorageClosedError: If the manager or PageFile is closed.
            InvalidPageIdError: If page_id is invalid.
            PageNotCachedError: If the page is not resident in the buffer pool.
            InvalidPinCountError: If pin_count is already 0.
        """
        self._check_not_closed()
        pid = validate_page_id(page_id)

        if pid not in self._page_table:
            raise PageNotCachedError(
                f"Cannot unpin PageId {pid.value}: page is not resident in the buffer pool."
            )

        fid = self._page_table[pid]
        frame = self._frames[fid]

        if frame.pin_count <= 0:
            raise InvalidPinCountError(
                f"Cannot unpin PageId {pid.value} in frame {fid}: pin_count is already 0."
            )

        frame.pin_count -= 1
        if is_dirty:
            frame.is_dirty = True

        if frame.pin_count == 0:
            self._replacer.unpin(fid)

    def flush_page(self, page_id: Union[PageId, int]) -> None:
        """Flush a specific cached page to disk if it is dirty.

        Clears the dirty flag upon successful write. If the page is not
        cached or not dirty, this operation is a safe no-op.

        Args:
            page_id: PageId or non-negative integer identifying the page.

        Raises:
            StorageClosedError: If the manager or PageFile is closed.
            InvalidPageIdError: If page_id is invalid.
        """
        self._check_not_closed()
        pid = validate_page_id(page_id)

        if pid in self._page_table:
            fid = self._page_table[pid]
            frame = self._frames[fid]
            if frame.is_dirty and frame.page is not None:
                self._page_file.write_page(pid, frame.page)
                frame.is_dirty = False

    def flush_all(self) -> None:
        """Flush all resident dirty pages to the underlying PageFile.

        Clears the dirty flag on all successfully written frames.

        Raises:
            StorageClosedError: If the manager or PageFile is closed.
        """
        self._check_not_closed()
        for frame in self._frames:
            if not frame.is_empty and frame.is_dirty and frame.page_id is not None and frame.page is not None:
                self._page_file.write_page(frame.page_id, frame.page)
                frame.is_dirty = False

    def delete_page(self, page_id: Union[PageId, int]) -> bool:
        """Remove a page from the buffer pool if it is unpinned.

        If the page is currently pinned, returns False (cannot be deleted).
        If the page is not cached, returns True.
        If the page is cached and unpinned, removes it from the page table,
        resets the frame, and returns the frame to the free list.

        Args:
            page_id: PageId or non-negative integer identifying the page.

        Returns:
            bool: True if page was removed or wasn't cached; False if pinned.

        Raises:
            StorageClosedError: If the manager or PageFile is closed.
            InvalidPageIdError: If page_id is invalid.
        """
        self._check_not_closed()
        pid = validate_page_id(page_id)

        if pid not in self._page_table:
            return True

        fid = self._page_table[pid]
        frame = self._frames[fid]

        if frame.is_pinned:
            return False

        # Remove from page table and replacer
        del self._page_table[pid]
        self._replacer.pin(fid)
        frame.reset()
        self._free_list.append(fid)
        return True

    def is_dirty(self, page_id: Union[PageId, int]) -> bool:
        """Check whether a cached page has unwritten modifications.

        Args:
            page_id: PageId or non-negative integer identifying the page.

        Returns:
            bool: True if cached and dirty; False otherwise.
        """
        pid = validate_page_id(page_id)
        if pid in self._page_table:
            return self._frames[self._page_table[pid]].is_dirty
        return False

    def get_pin_count(self, page_id: Union[PageId, int]) -> int:
        """Return the current pin count of a cached page.

        Args:
            page_id: PageId or non-negative integer identifying the page.

        Returns:
            int: Pin count of the cached page.

        Raises:
            PageNotCachedError: If the page is not currently in the buffer pool.
        """
        pid = validate_page_id(page_id)
        if pid not in self._page_table:
            raise PageNotCachedError(
                f"PageId {pid.value} is not resident in the buffer pool."
            )
        return self._frames[self._page_table[pid]].pin_count

    def contains_page(self, page_id: Union[PageId, int]) -> bool:
        """Return whether a page is currently cached in the buffer pool."""
        pid = validate_page_id(page_id)
        return pid in self._page_table

    def close(self) -> None:
        """Flush all dirty pages and mark the buffer pool manager as closed."""
        if not self._closed:
            try:
                if not self._page_file.is_closed:
                    self.flush_all()
            finally:
                self._closed = True

    def __enter__(self) -> "BufferPoolManager":
        """Enter runtime context for context manager usage."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit runtime context, flushing dirty pages and closing the manager."""
        self.close()

    def __repr__(self) -> str:
        status = "closed" if self._closed else f"open, cached={self.cached_page_count}/{self._pool_size}"
        return f"BufferPoolManager(pool_size={self._pool_size}, status='{status}')"
