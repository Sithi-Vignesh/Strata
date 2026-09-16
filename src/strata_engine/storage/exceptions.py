"""Exceptions for the Strata storage engine.

Provides structured, domain-specific exception types for page handling,
slotted page record operations, storage file lifecycle, and disk layout violations.
"""


class StorageError(Exception):
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
