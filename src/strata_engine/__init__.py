"""Strata Engine Package.

Provides the custom relational database engine for the Strata system.
"""

from strata_engine.engine import StrataEngine
from strata_engine.storage import (
    PAGE_SIZE,
    InsufficientSpaceError,
    InvalidPageIdError,
    InvalidSlotIdError,
    Page,
    PageFile,
    PageId,
    PageNotFoundError,
    PageSizeError,
    RecordId,
    RecordNotFoundError,
    RecordSizeError,
    SlottedPage,
    SlottedPageCorruptionError,
    StorageClosedError,
    StorageCorruptionError,
    StorageError,
)

__all__ = [
    "StrataEngine",
    "PAGE_SIZE",
    "Page",
    "PageId",
    "PageFile",
    "RecordId",
    "SlottedPage",
    "StorageError",
    "PageSizeError",
    "InvalidPageIdError",
    "PageNotFoundError",
    "StorageClosedError",
    "StorageCorruptionError",
    "RecordSizeError",
    "RecordNotFoundError",
    "InsufficientSpaceError",
    "InvalidSlotIdError",
    "SlottedPageCorruptionError",
]
