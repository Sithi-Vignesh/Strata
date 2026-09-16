"""Slotted-page binary storage abstraction.

A SlottedPage organizes a fixed-size 4096-byte Page into:
1. An 8-byte Page Header at the beginning (growing forward from offset 0).
2. A Slot Directory with 4-byte entries (offset, length) (growing forward from offset 8).
3. Contiguous free space in the middle.
4. Record byte data allocated from the end of the page (growing backward from offset 4096).

Slot representations:
- Active non-empty record: (free_space_offset <= offset < PAGE_SIZE, length > 0)
- Active empty record: (offset=PAGE_SIZE, length=0)
- Deleted/unused slot: (offset=0, length=0)

Enforces strict binary layout validation, stable slot indexing, compaction,
and structural corruption detection.
"""

import struct
from typing import Any, List, Optional, Tuple, Union

from strata_engine.storage.exceptions import (
    InsufficientSpaceError,
    InvalidSlotIdError,
    PageSizeError,
    RecordNotFoundError,
    RecordSizeError,
    SlottedPageCorruptionError,
)
from strata_engine.storage.page import PAGE_SIZE, Page
from strata_engine.storage.page_id import PageId, validate_page_id

# Binary layout constants
PAGE_HEADER_MAGIC: int = 0x5350  # ASCII 'S', 'P'
PAGE_HEADER_FORMAT: str = ">HHHH"  # (magic, flags, slot_count, free_space_offset)
PAGE_HEADER_SIZE: int = struct.calcsize(PAGE_HEADER_FORMAT)  # 8 bytes

SLOT_ENTRY_FORMAT: str = ">HH"  # (offset, length)
SLOT_ENTRY_SIZE: int = struct.calcsize(SLOT_ENTRY_FORMAT)  # 4 bytes

# Authoritative slot status sentinels
DELETED_SLOT_OFFSET: int = 0
LIVE_EMPTY_RECORD_OFFSET: int = PAGE_SIZE  # 4096 points to boundary, length 0

# Maximum record size possible on an empty page (PAGE_SIZE - header - 1 slot entry)
MAX_RECORD_SIZE: int = PAGE_SIZE - PAGE_HEADER_SIZE - SLOT_ENTRY_SIZE  # 4084 bytes


class SlottedPage:
    """Record-oriented page holding variable-length raw byte records.

    Provides insertion, retrieval, deletion, defragmentation compaction,
    and byte-level integrity verification.
    """

    __slots__ = (
        "_buffer",
        "_page_id",
        "_flags",
        "_slot_count",
        "_free_space_offset",
        "_slots",
    )

    def __init__(
        self,
        data: Optional[Union[bytes, bytearray]] = None,
        page_id: Optional[Union[PageId, int]] = None,
    ) -> None:
        """Initialize or parse a SlottedPage.

        Args:
            data: Optional binary buffer of exactly PAGE_SIZE bytes. If None,
                initializes a new, empty slotted page.
            page_id: Optional PageId associated with this page.

        Raises:
            PageSizeError: If data length is not PAGE_SIZE.
            SlottedPageCorruptionError: If data violates binary format invariants.
        """
        self._page_id: Optional[PageId] = (
            validate_page_id(page_id) if page_id is not None else None
        )

        if data is None:
            # Initialize empty slotted page
            self._buffer: bytearray = bytearray(PAGE_SIZE)
            self._flags: int = 0
            self._slot_count: int = 0
            self._free_space_offset: int = PAGE_SIZE
            self._slots: List[Tuple[int, int]] = []
            self._write_header()
        else:
            if len(data) != PAGE_SIZE:
                raise PageSizeError(
                    f"SlottedPage data must be exactly {PAGE_SIZE} bytes, got {len(data)}."
                )
            self._buffer = bytearray(data)
            self._parse_and_validate()

    @property
    def page_id(self) -> Optional[PageId]:
        """Return the associated PageId, if set."""
        return self._page_id

    @page_id.setter
    def page_id(self, value: Optional[Union[PageId, int]]) -> None:
        """Set or update the associated PageId."""
        self._page_id = validate_page_id(value) if value is not None else None

    @property
    def slot_count(self) -> int:
        """Return total number of allocated slot entries (active + deleted)."""
        return self._slot_count

    @property
    def live_record_count(self) -> int:
        """Return the number of active, non-deleted records (including empty records)."""
        return sum(1 for offset, _ in self._slots if offset != DELETED_SLOT_OFFSET)

    @property
    def free_space_offset(self) -> int:
        """Return the byte offset where non-empty record allocation starts."""
        return self._free_space_offset

    @property
    def slot_directory_end(self) -> int:
        """Return the byte offset where the slot directory ends."""
        return PAGE_HEADER_SIZE + self._slot_count * SLOT_ENTRY_SIZE

    @property
    def contiguous_free_space_bytes(self) -> int:
        """Return the number of contiguous unallocated bytes between slot directory and records."""
        return self._free_space_offset - self.slot_directory_end

    @property
    def total_free_space_bytes(self) -> int:
        """Return total unallocated and dead space available on the page."""
        live_bytes = sum(
            length for offset, length in self._slots if offset != DELETED_SLOT_OFFSET
        )
        return PAGE_SIZE - self.slot_directory_end - live_bytes

    def has_space_for(self, data_length: int) -> bool:
        """Return whether the page can accommodate a record of the given size.

        Considers existing deleted slots that can be reused without expanding
        the slot directory.
        """
        if data_length < 0 or data_length > MAX_RECORD_SIZE:
            return False

        has_deleted_slot = any(
            offset == DELETED_SLOT_OFFSET for offset, _ in self._slots
        )
        required_space = data_length + (0 if has_deleted_slot else SLOT_ENTRY_SIZE)
        return self.total_free_space_bytes >= required_space

    @classmethod
    def from_page(
        cls, page: Page, page_id: Optional[Union[PageId, int]] = None
    ) -> "SlottedPage":
        """Construct a SlottedPage from an existing Page instance."""
        return cls(data=page.to_bytes(), page_id=page_id)

    def to_page(self) -> Page:
        """Convert the SlottedPage into an immutable Page instance."""
        return Page(bytes(self._buffer))

    def to_bytes(self) -> bytes:
        """Return the raw 4096 bytes of the page."""
        return bytes(self._buffer)

    def _write_header(self) -> None:
        """Serialize the page header into the internal buffer."""
        struct.pack_into(
            PAGE_HEADER_FORMAT,
            self._buffer,
            0,
            PAGE_HEADER_MAGIC,
            self._flags,
            self._slot_count,
            self._free_space_offset,
        )

    def _write_slot(self, slot_id: int, offset: int, length: int) -> None:
        """Serialize a single slot entry into the internal buffer."""
        slot_pos = PAGE_HEADER_SIZE + slot_id * SLOT_ENTRY_SIZE
        struct.pack_into(SLOT_ENTRY_FORMAT, self._buffer, slot_pos, offset, length)

    def _parse_and_validate(self) -> None:
        """Parse and validate internal byte buffer against slotted page format invariants.

        Raises:
            SlottedPageCorruptionError: If layout, boundaries, or offsets are invalid.
        """
        try:
            magic, flags, slot_count, free_space_offset = struct.unpack_from(
                PAGE_HEADER_FORMAT, self._buffer, 0
            )
        except struct.error as err:
            raise SlottedPageCorruptionError(
                f"Failed to unpack header from page: {err}"
            ) from err

        if magic != PAGE_HEADER_MAGIC:
            raise SlottedPageCorruptionError(
                f"Invalid slotted page magic number: 0x{magic:04x}, expected 0x{PAGE_HEADER_MAGIC:04x}."
            )

        slot_directory_end = PAGE_HEADER_SIZE + slot_count * SLOT_ENTRY_SIZE
        if (
            slot_directory_end > free_space_offset
            or free_space_offset > PAGE_SIZE
            or free_space_offset < PAGE_HEADER_SIZE
        ):
            raise SlottedPageCorruptionError(
                f"Corrupt page boundaries: slot_directory_end={slot_directory_end}, "
                f"free_space_offset={free_space_offset}, PAGE_SIZE={PAGE_SIZE}."
            )

        self._flags = flags
        self._slot_count = slot_count
        self._free_space_offset = free_space_offset
        self._slots = []

        live_intervals: List[Tuple[int, int, int]] = []  # (offset, end_offset, slot_id)

        for slot_id in range(slot_count):
            slot_pos = PAGE_HEADER_SIZE + slot_id * SLOT_ENTRY_SIZE
            offset, length = struct.unpack_from(SLOT_ENTRY_FORMAT, self._buffer, slot_pos)

            if offset == DELETED_SLOT_OFFSET:
                if length != 0:
                    raise SlottedPageCorruptionError(
                        f"Deleted slot {slot_id} has non-zero length: {length}."
                    )
            elif length == 0:
                # Live empty record representation must use LIVE_EMPTY_RECORD_OFFSET (PAGE_SIZE)
                if offset != LIVE_EMPTY_RECORD_OFFSET:
                    raise SlottedPageCorruptionError(
                        f"Invalid live zero-length record representation in slot {slot_id}: "
                        f"offset={offset}, expected LIVE_EMPTY_RECORD_OFFSET ({LIVE_EMPTY_RECORD_OFFSET})."
                    )
            else:
                # Live non-empty record
                if offset < free_space_offset or (offset + length) > PAGE_SIZE:
                    raise SlottedPageCorruptionError(
                        f"Slot {slot_id} points out of bounds: offset={offset}, "
                        f"length={length}, free_space_offset={free_space_offset}."
                    )
                live_intervals.append((offset, offset + length, slot_id))

            self._slots.append((offset, length))

        # Check for overlapping records among live non-empty slots
        live_intervals.sort(key=lambda item: item[0])
        for i in range(len(live_intervals) - 1):
            curr_start, curr_end, curr_slot = live_intervals[i]
            next_start, _, next_slot = live_intervals[i + 1]
            if curr_end > next_start:
                raise SlottedPageCorruptionError(
                    f"Overlapping records detected between slot {curr_slot} "
                    f"([{curr_start}, {curr_end}]) and slot {next_slot} "
                    f"(starts at {next_start})."
                )

    def insert_record(self, data: Union[bytes, bytearray]) -> int:
        """Insert a variable-length record into the slotted page.

        Note:
            Returns a page-local int slot ID (slot_id). A higher-level storage
            abstraction (such as a table or heap file manager) is responsible
            for combining the PageId and slot_id into a full RecordId.

        Args:
            data: Binary record to store (can be empty b"").

        Returns:
            int: Page-local slot index (slot_id) assigned to the record.

        Raises:
            TypeError: If data is not bytes or bytearray.
            RecordSizeError: If record size exceeds MAX_RECORD_SIZE.
            InsufficientSpaceError: If page has insufficient space even after compaction.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"Record data must be bytes-like, got {type(data).__name__}."
            )

        rec_len = len(data)
        if rec_len > MAX_RECORD_SIZE:
            raise RecordSizeError(
                f"Record of {rec_len} bytes exceeds maximum page capacity of {MAX_RECORD_SIZE} bytes."
            )

        # Check for deleted slot reuse
        reusable_slot_id: Optional[int] = None
        for i, (offset, _) in enumerate(self._slots):
            if offset == DELETED_SLOT_OFFSET:
                reusable_slot_id = i
                break

        slot_entry_overhead = 0 if reusable_slot_id is not None else SLOT_ENTRY_SIZE
        needed_space = rec_len + slot_entry_overhead

        # Check total capacity
        if self.total_free_space_bytes < needed_space:
            raise InsufficientSpaceError(
                f"Insufficient space for {rec_len}-byte record: "
                f"need {needed_space} bytes, total available {self.total_free_space_bytes} bytes."
            )

        # If contiguous space is insufficient due to fragmentation, trigger compaction
        if self.contiguous_free_space_bytes < needed_space:
            self.compact()

        # Allocate slot index
        if reusable_slot_id is not None:
            slot_id = reusable_slot_id
        else:
            slot_id = self._slot_count
            self._slot_count += 1

        # Place record
        if rec_len == 0:
            # Explicit live empty record representation
            new_offset = LIVE_EMPTY_RECORD_OFFSET
            # free_space_offset does not decrease for zero-byte records
        else:
            new_offset = self._free_space_offset - rec_len
            self._buffer[new_offset : new_offset + rec_len] = data
            self._free_space_offset = new_offset

        # Update slot directory in memory
        if slot_id < len(self._slots):
            self._slots[slot_id] = (new_offset, rec_len)
        else:
            self._slots.append((new_offset, rec_len))

        # Persist changes into page buffer
        self._write_header()
        self._write_slot(slot_id, new_offset, rec_len)

        return slot_id

    def get_record(self, slot_id: int) -> bytes:
        """Retrieve record bytes by slot index.

        Args:
            slot_id: Slot index within the slot directory.

        Returns:
            bytes of the stored record (b"" for empty records).

        Raises:
            InvalidSlotIdError: If slot_id is invalid or out of range.
            RecordNotFoundError: If slot is deleted.
            SlottedPageCorruptionError: If record boundaries are invalid.
        """
        if (
            isinstance(slot_id, bool)
            or not isinstance(slot_id, int)
            or slot_id < 0
            or slot_id >= self._slot_count
        ):
            raise InvalidSlotIdError(
                f"Invalid slot_id: {slot_id!r}. Must be an integer in range [0, {self._slot_count})."
            )

        offset, length = self._slots[slot_id]
        if offset == DELETED_SLOT_OFFSET:
            raise RecordNotFoundError(f"Record at slot {slot_id} is deleted.")

        if length == 0:
            if offset != LIVE_EMPTY_RECORD_OFFSET:
                raise SlottedPageCorruptionError(
                    f"Corrupt live empty record in slot {slot_id}: offset={offset}."
                )
            return b""

        if offset < self._free_space_offset or (offset + length) > PAGE_SIZE:
            raise SlottedPageCorruptionError(
                f"Corrupt record boundaries at slot {slot_id}: "
                f"offset={offset}, length={length}, PAGE_SIZE={PAGE_SIZE}."
            )

        return bytes(self._buffer[offset : offset + length])

    def delete_record(self, slot_id: int) -> None:
        """Mark a record slot as deleted.

        Space previously occupied by non-empty records becomes fragmented
        until compaction occurs.

        Args:
            slot_id: Slot index of the record to delete.

        Raises:
            InvalidSlotIdError: If slot_id is invalid or out of range.
            RecordNotFoundError: If the slot is already deleted.
        """
        if (
            isinstance(slot_id, bool)
            or not isinstance(slot_id, int)
            or slot_id < 0
            or slot_id >= self._slot_count
        ):
            raise InvalidSlotIdError(
                f"Invalid slot_id: {slot_id!r}. Must be an integer in range [0, {self._slot_count})."
            )

        offset, length = self._slots[slot_id]
        if offset == DELETED_SLOT_OFFSET:
            raise RecordNotFoundError(
                f"Cannot delete record at slot {slot_id}: record is already deleted."
            )

        # Invalidate slot directory entry to authoritative deleted sentinel (0, 0)
        self._slots[slot_id] = (DELETED_SLOT_OFFSET, 0)
        self._write_slot(slot_id, DELETED_SLOT_OFFSET, 0)

    def compact(self) -> None:
        """Defragment the page by packing live records contiguously at the end.

        Maintains strictly stable slot IDs so that existing RecordId references
        remain valid.

        Raises:
            SlottedPageCorruptionError: If live records and slot directory exceed PAGE_SIZE.
        """
        new_buffer = bytearray(PAGE_SIZE)
        new_free_space_offset = PAGE_SIZE
        new_slots: List[Tuple[int, int]] = []

        live_bytes = sum(
            length for offset, length in self._slots if offset != DELETED_SLOT_OFFSET
        )
        slot_dir_end = PAGE_HEADER_SIZE + len(self._slots) * SLOT_ENTRY_SIZE
        if slot_dir_end + live_bytes > PAGE_SIZE:
            raise SlottedPageCorruptionError(
                f"Compaction failed: live records ({live_bytes} bytes) and slot directory "
                f"({slot_dir_end} bytes) exceed PAGE_SIZE ({PAGE_SIZE})."
            )

        # Pack all live non-empty records from the end of the new buffer downwards
        for slot_id, (offset, length) in enumerate(self._slots):
            if offset == DELETED_SLOT_OFFSET:
                # Deleted slot: preserve stable index with (0, 0)
                new_slots.append((DELETED_SLOT_OFFSET, 0))
            elif length == 0:
                # Live empty record: preserve stable index with (LIVE_EMPTY_RECORD_OFFSET, 0)
                new_slots.append((LIVE_EMPTY_RECORD_OFFSET, 0))
            else:
                # Live non-empty record: pack data
                record_data = self._buffer[offset : offset + length]
                new_free_space_offset -= length
                new_buffer[new_free_space_offset : new_free_space_offset + length] = (
                    record_data
                )
                new_slots.append((new_free_space_offset, length))

        # Write new header and slot directory
        self._buffer = new_buffer
        self._free_space_offset = new_free_space_offset
        self._slots = new_slots

        self._write_header()
        for slot_id, (offset, length) in enumerate(self._slots):
            self._write_slot(slot_id, offset, length)

    def __repr__(self) -> str:
        pid_str = f"page_id={self._page_id.value}, " if self._page_id else ""
        return (
            f"SlottedPage({pid_str}slots={self._slot_count}, "
            f"live={self.live_record_count}, free_bytes={self.total_free_space_bytes})"
        )
