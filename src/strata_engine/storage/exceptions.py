"""Exceptions for the Strata storage engine.

Provides structured, domain-specific exception types for page handling,
storage file lifecycle, and disk layout violations.
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
