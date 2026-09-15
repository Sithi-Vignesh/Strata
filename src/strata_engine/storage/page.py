"""Fixed-size storage page abstraction.

A Page represents a fixed-size byte buffer (default 4096 bytes) corresponding
directly to a single disk block in Strata's page-oriented storage layer.
"""

from typing import Any, Optional, Union
from strata_engine.storage.exceptions import PageSizeError

# Single authoritative page-size constant (4096 bytes / 4 KB)
PAGE_SIZE: int = 4096


class Page:
    """Fixed-size binary page holding exactly PAGE_SIZE bytes.

    Provides safe byte access and enforces the page size invariant strictly:
    neither undersized nor oversized byte sequences are permitted.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Optional[Union[bytes, bytearray]] = None) -> None:
        """Initialize a fixed-size Page.

        Args:
            data: Optional binary data of length PAGE_SIZE. If None, a blank
                zero-filled page is created.

        Raises:
            PageSizeError: If data length is not exactly PAGE_SIZE.
        """
        if data is None:
            self._data: bytearray = bytearray(PAGE_SIZE)
        else:
            if len(data) != PAGE_SIZE:
                raise PageSizeError(
                    f"Page data must be exactly {PAGE_SIZE} bytes, got {len(data)} bytes."
                )
            self._data = bytearray(data)

    @classmethod
    def blank(cls) -> "Page":
        """Create a new zero-filled page of size PAGE_SIZE."""
        return cls()

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray]) -> "Page":
        """Construct a Page from an exact PAGE_SIZE byte sequence.

        Args:
            data: Binary sequence of length PAGE_SIZE.

        Returns:
            Page instance wrapping a copy of the data.

        Raises:
            PageSizeError: If data length is not exactly PAGE_SIZE.
        """
        return cls(data)

    def to_bytes(self) -> bytes:
        """Return an immutable bytes copy of the page data.

        Returns:
            bytes of length PAGE_SIZE.
        """
        return bytes(self._data)

    @property
    def size(self) -> int:
        """Return the fixed size of the page in bytes."""
        return PAGE_SIZE

    def __len__(self) -> int:
        return PAGE_SIZE

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Page):
            return self._data == other._data
        if isinstance(other, (bytes, bytearray)):
            return self._data == other
        return False

    def __repr__(self) -> str:
        return f"Page(size={PAGE_SIZE}, non_zero_bytes={sum(1 for b in self._data if b != 0)})"
