"""Exceptions for the Strata storage engine.

Provides structured, domain-specific exception types for page handling,
slotted page record operations, storage file lifecycle, and disk layout violations.
"""


from strata_engine.exceptions import StrataError


class StorageError(StrataError):
    """Base exception for all errors within the storage engine."""


class PageSizeError(StorageError):
    """Raised when page binary data does not match the authoritative PAGE_SIZE."""


class InvalidPageIdError(StorageError):
    """Raised when a page identifier is negative, invalid type, or malformed."""


class PageNotFoundError(StorageError):
    """Raised when attempting to access a page ID that has not been allocated."""


class StorageClosedError(StorageError):
    """Raised when storage operations are attempted on a closed PageFile."""


class StorageCorruptionError(StorageError):
    """Raised when storage file data or header layout violates format invariants."""


class RecordSizeError(StorageError):
    """Raised when a record size exceeds the maximum possible space in a page."""


class RecordNotFoundError(StorageError):
    """Raised when accessing a slot that does not exist or has been deleted."""


class InsufficientSpaceError(StorageError):
    """Raised when a slotted page does not have enough free space to store a record."""


class InvalidSlotIdError(StorageError):
    """Raised when a slot identifier is negative, not an integer, or invalid."""


class SlottedPageCorruptionError(StorageCorruptionError):
    """Raised when a slotted page binary layout violates structure invariants."""


class BufferPoolFullError(StorageError):
    """Raised when all buffer pool frames are pinned and a new page cannot be accommodated."""


class PageNotCachedError(StorageError):
    """Raised when an operation targets a page that is not currently resident in the buffer pool."""


class InvalidPinCountError(StorageError):
    """Raised when an invalid pin count operation occurs (such as unpinning an unpinned page)."""


class BPlusTreeError(StorageError):
    """Base exception for persistent B+ tree storage failures."""


class UnsupportedKeyTypeError(BPlusTreeError):
    """Raised when a B+ tree is configured with an unsupported key type."""


class KeyTypeMismatchError(BPlusTreeError):
    """Raised when an opened tree does not match an expected key type."""


class InvalidKeyError(BPlusTreeError):
    """Raised when a key is null, has the wrong runtime type, or is out of range."""


class KeyTooLargeError(BPlusTreeError):
    """Raised when one encoded key cannot be represented in a B+ tree node."""


class BPlusTreeCorruptionError(StorageCorruptionError):
    """Raised when a persistent B+ tree header or node is malformed."""
