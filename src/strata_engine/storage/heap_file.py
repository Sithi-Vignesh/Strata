"""Heap file record collection abstraction.

A HeapFile manages an unordered collection of variable-length raw byte records
spanning multiple slotted pages backed by a BufferPoolManager.
Enforces first-fit page selection, transparent page allocation, stable RecordId
addressing, and leak-proof pin/unpin lifecycle.
"""

from typing import Iterator, List, Optional, Tuple, Union

from strata_engine.storage.buffer_pool import BufferPoolManager
from strata_engine.storage.exceptions import (
    RecordSizeError,
    StorageClosedError,
)
from strata_engine.storage.page_id import PageId
from strata_engine.storage.record_id import RecordId
from strata_engine.storage.slotted_page import MAX_RECORD_SIZE, SlottedPage


class HeapFile:
    """Manages an unordered collection of records stored across multiple slotted pages.

    Architectural constraints (Phase 4):
    - 1:1 mapping between PageFile, BufferPoolManager, and HeapFile.
    - All pages in the underlying PageFile (PageId 0 to page_count - 1) belong
      exclusively to this HeapFile.
    - Records are addressed by immutable RecordId(page_id, slot_id).
    - Page allocation uses deterministic first-fit linear scanning.
    - Scans never hold pages pinned across generator yields.
    """

    def __init__(self, buffer_pool_manager: BufferPoolManager) -> None:
        """Initialize a HeapFile backed by a BufferPoolManager.

        Args:
            buffer_pool_manager: BufferPoolManager instance for page caching and I/O.

        Raises:
            TypeError: If buffer_pool_manager is not an instance of BufferPoolManager.
            StorageClosedError: If the buffer pool manager is closed.
        """
        if not isinstance(buffer_pool_manager, BufferPoolManager):
            raise TypeError(
                f"Expected BufferPoolManager instance, got {type(buffer_pool_manager).__name__}."
            )
        if buffer_pool_manager.is_closed:
            raise StorageClosedError(
                "Cannot initialize HeapFile on a closed BufferPoolManager."
            )

        self._bpm: BufferPoolManager = buffer_pool_manager

    @property
    def buffer_pool_manager(self) -> BufferPoolManager:
        """Return the underlying BufferPoolManager instance."""
        return self._bpm

    @property
    def page_count(self) -> int:
        """Return the number of allocated pages currently in the heap file."""
        return self._bpm.page_file.page_count

    def insert_record(self, data: Union[bytes, bytearray]) -> RecordId:
        """Insert a variable-length raw byte record into the heap file.

        Uses deterministic first-fit linear scanning across existing pages.
        If no existing page can fit the record, allocates a new page via
        the BufferPoolManager.

        Args:
            data: Binary record bytes or bytearray (can be empty b"").

        Returns:
            RecordId: Immutable identifier containing (page_id, slot_id).

        Raises:
            TypeError: If data is not bytes or bytearray.
            RecordSizeError: If record size exceeds MAX_RECORD_SIZE (4084 bytes).
            StorageClosedError: If the underlying storage is closed.
            BufferPoolFullError: If buffer pool frames are exhausted and all are pinned.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"Record data must be bytes or bytearray, got {type(data).__name__}."
            )

        rec_len = len(data)
        if rec_len > MAX_RECORD_SIZE:
            raise RecordSizeError(
                f"Record of {rec_len} bytes exceeds maximum page capacity of {MAX_RECORD_SIZE} bytes."
            )

        # First-fit linear scan across existing pages
        current_count = self.page_count
        for pid_val in range(current_count):
            pid = PageId(pid_val)
            page = self._bpm.fetch_page(pid)
            inserted_slot: Optional[int] = None
            is_dirty = False
            try:
                sp = SlottedPage.from_page(page, page_id=pid)
                if sp.has_space_for(rec_len):
                    inserted_slot = sp.insert_record(data)
                    page.write_bytes(sp.to_bytes())
                    is_dirty = True
            finally:
                self._bpm.unpin_page(pid, is_dirty=is_dirty)

            if inserted_slot is not None:
                return RecordId(pid, inserted_slot)

        # No existing page had enough space (or heap is brand new with 0 pages).
        # Allocate a new page through BufferPoolManager.
        new_pid, new_page = self._bpm.new_page()
        is_dirty = True
        try:
            sp = SlottedPage(page_id=new_pid)
            slot_id = sp.insert_record(data)
            new_page.write_bytes(sp.to_bytes())
            return RecordId(new_pid, slot_id)
        finally:
            self._bpm.unpin_page(new_pid, is_dirty=is_dirty)

    def get_record(self, record_id: RecordId) -> bytes:
        """Retrieve record bytes by its RecordId.

        Args:
            record_id: Immutable RecordId specifying (page_id, slot_id).

        Returns:
            bytes: The stored record byte payload.

        Raises:
            TypeError: If record_id is not an instance of RecordId.
            RecordNotFoundError: If slot is deleted or unallocated.
            PageNotFoundError: If page_id is out of bounds.
            StorageClosedError: If the underlying storage is closed.
        """
        if not isinstance(record_id, RecordId):
            raise TypeError(
                f"Expected RecordId instance, got {type(record_id).__name__}."
            )

        pid = record_id.page_id
        slot_id = record_id.slot_id

        page = self._bpm.fetch_page(pid)
        try:
            sp = SlottedPage.from_page(page, page_id=pid)
            return sp.get_record(slot_id)
        finally:
            self._bpm.unpin_page(pid, is_dirty=False)

    def delete_record(self, record_id: RecordId) -> None:
        """Delete a record by its RecordId.

        Marks the slot as deleted, enabling future slot reuse. Does not physically
        truncate or remove pages from the file.

        Args:
            record_id: Immutable RecordId specifying (page_id, slot_id).

        Raises:
            TypeError: If record_id is not an instance of RecordId.
            RecordNotFoundError: If slot is already deleted or unallocated.
            PageNotFoundError: If page_id is out of bounds.
            StorageClosedError: If the underlying storage is closed.
        """
        if not isinstance(record_id, RecordId):
            raise TypeError(
                f"Expected RecordId instance, got {type(record_id).__name__}."
            )

        pid = record_id.page_id
        slot_id = record_id.slot_id

        page = self._bpm.fetch_page(pid)
        is_dirty = False
        try:
            sp = SlottedPage.from_page(page, page_id=pid)
            sp.delete_record(slot_id)
            page.write_bytes(sp.to_bytes())
            is_dirty = True
        finally:
            self._bpm.unpin_page(pid, is_dirty=is_dirty)

    def scan_records(self) -> Iterator[Tuple[RecordId, bytes]]:
        """Iterate over all active records across all pages in the heap file.

        Guarantees:
        - Pages are visited in ascending PageId order.
        - Records on each page are visited in ascending slot_id order.
        - Deleted slots are omitted.
        - Live empty records (b"") are included.
        - Pages are unpinned before yielding records; early break from iteration
          never leaks pinned pages.
        - Operates correctly even when pool_size = 1.

        Yields:
            Tuple[RecordId, bytes]: Pair of (record_id, record_bytes).

        Raises:
            StorageClosedError: If the underlying storage is closed.
        """
        current_count = self.page_count
        for pid_val in range(current_count):
            pid = PageId(pid_val)
            page = self._bpm.fetch_page(pid)
            page_records: List[Tuple[RecordId, bytes]] = []
            try:
                sp = SlottedPage.from_page(page, page_id=pid)
                for slot_id in range(sp.slot_count):
                    try:
                        rec_data = sp.get_record(slot_id)
                        page_records.append((RecordId(pid, slot_id), rec_data))
                    except Exception:
                        # Deleted slot or unallocated: skip
                        continue
            finally:
                self._bpm.unpin_page(pid, is_dirty=False)

            for rid, rec_data in page_records:
                yield rid, rec_data

    def __repr__(self) -> str:
        status = "closed" if self._bpm.is_closed else f"open, pages={self.page_count}"
        return f"HeapFile(pages={self.page_count}, status='{status}')"
