"""Disk-backed page-file storage abstraction.

Manages persistent binary storage files composed of contiguous, fixed-size pages.
Maps PageId N to deterministic byte offset: N * PAGE_SIZE.
"""

import io
from pathlib import Path
from typing import Any, BinaryIO, Optional, Union

from strata_engine.storage.exceptions import (
    PageNotFoundError,
    StorageClosedError,
    StorageCorruptionError,
)
from strata_engine.storage.page import PAGE_SIZE, Page
from strata_engine.storage.page_id import PageId, validate_page_id


class PageFile:
    """Disk-backed storage manager for fixed-size database pages.

    Manages binary page files where every page occupies exactly PAGE_SIZE bytes.
    Enforces deterministic zero-filled page allocation, offset-based indexing,
    bounds checking, and safe file closure across operating systems.
    """

    def __init__(self, path: Union[Path, str]) -> None:
        """Open or create a disk-backed page file.

        Args:
            path: Filesystem path to the storage file.

        Raises:
            StorageCorruptionError: If the file exists and its size is not
                an exact multiple of PAGE_SIZE.
        """
        self._path: Path = Path(path).resolve()
        self._closed: bool = False

        # Ensure parent directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Create file if it doesn't already exist without truncating if it does
        if not self._path.exists():
            with open(self._path, "xb"):
                pass

        # Open in binary read/update mode
        self._file: BinaryIO = open(self._path, "r+b")

        # Verify initial file size invariant
        self._file.seek(0, io.SEEK_END)
        size = self._file.tell()
        if size % PAGE_SIZE != 0:
            self._file.close()
            self._closed = True
            raise StorageCorruptionError(
                f"Storage file at '{self._path}' is corrupt: "
                f"file size ({size} bytes) is not an exact multiple of PAGE_SIZE ({PAGE_SIZE})."
            )

    @property
    def path(self) -> Path:
        """Return the absolute path of the page file."""
        return self._path

    @property
    def is_closed(self) -> bool:
        """Return whether the page file is closed."""
        return self._closed

    def _check_not_closed(self) -> None:
        """Raise StorageClosedError if operations are attempted after closure."""
        if self._closed or self._file.closed:
            raise StorageClosedError(
                f"Operation attempted on closed PageFile: '{self._path}'"
            )

    @property
    def page_count(self) -> int:
        """Return the current number of allocated pages in the storage file."""
        self._check_not_closed()
        self._file.seek(0, io.SEEK_END)
        return self._file.tell() // PAGE_SIZE

    def __len__(self) -> int:
        """Return the current number of allocated pages."""
        return self.page_count

    def allocate_page(self) -> PageId:
        """Allocate a new page at the end of the file initialized with zero-filled bytes.

        Returns:
            PageId assigned to the newly allocated page.

        Raises:
            StorageClosedError: If the page file is closed.
        """
        self._check_not_closed()
        self._file.seek(0, io.SEEK_END)
        offset = self._file.tell()
        new_page_id = PageId(offset // PAGE_SIZE)

        # Write deterministic zero-filled page
        blank_bytes = b"\x00" * PAGE_SIZE
        self._file.write(blank_bytes)
        self._file.flush()

        return new_page_id

    def read_page(self, page_id: Union[PageId, int]) -> Page:
        """Read a page from the storage file by its PageId.

        Args:
            page_id: PageId or non-negative integer identifying the page.

        Returns:
            Page containing the binary data stored at the page offset.

        Raises:
            StorageClosedError: If the page file is closed.
            InvalidPageIdError: If page_id is negative or not an integer.
            PageNotFoundError: If page_id has not been allocated.
            StorageCorruptionError: If reading fails to retrieve PAGE_SIZE bytes.
        """
        self._check_not_closed()
        pid = validate_page_id(page_id)

        current_count = self.page_count
        if pid.value >= current_count:
            raise PageNotFoundError(
                f"PageId {pid.value} does not exist in '{self._path}'. "
                f"Current allocated pages: {current_count}."
            )

        offset = pid.value * PAGE_SIZE
        self._file.seek(offset)
        raw_data = self._file.read(PAGE_SIZE)

        if len(raw_data) != PAGE_SIZE:
            raise StorageCorruptionError(
                f"Incomplete page read at PageId {pid.value} (offset {offset}): "
                f"expected {PAGE_SIZE} bytes, received {len(raw_data)}."
            )

        return Page.from_bytes(raw_data)

    def write_page(self, page_id: Union[PageId, int], page: Page) -> None:
        """Write page data to the storage file at the offset specified by PageId.

        Args:
            page_id: PageId or non-negative integer identifying the page.
            page: Page instance containing PAGE_SIZE bytes to write.

        Raises:
            StorageClosedError: If the page file is closed.
            InvalidPageIdError: If page_id is negative or not an integer.
            PageNotFoundError: If page_id has not been allocated.
            TypeError: If page is not an instance of Page.
        """
        self._check_not_closed()
        pid = validate_page_id(page_id)

        if not isinstance(page, Page):
            raise TypeError(f"Expected Page instance, got {type(page).__name__}")

        current_count = self.page_count
        if pid.value >= current_count:
            raise PageNotFoundError(
                f"Cannot write to unallocated PageId {pid.value} in '{self._path}'. "
                f"Current allocated pages: {current_count}. Allocate the page first."
            )

        offset = pid.value * PAGE_SIZE
        self._file.seek(offset)
        self._file.write(page.to_bytes())
        self._file.flush()

    def close(self) -> None:
        """Flush and close the underlying binary file safely."""
        if not self._closed:
            try:
                if hasattr(self, "_file") and not self._file.closed:
                    self._file.flush()
                    self._file.close()
            finally:
                self._closed = True

    def __enter__(self) -> "PageFile":
        """Enter runtime context for context manager usage."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit runtime context and close the page file."""
        self.close()

    def __repr__(self) -> str:
        status = "closed" if self._closed else f"open, pages={self.page_count}"
        return f"PageFile(path='{self._path}', status='{status}')"
