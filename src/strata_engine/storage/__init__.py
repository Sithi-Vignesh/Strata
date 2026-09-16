"""Strata Storage Engine Package.

Provides fixed-size pages, validated page identifiers, disk-backed page files,
slotted pages, and record identifiers for record-oriented storage.
"""

from strata_engine.storage.exceptions import (
    InsufficientSpaceError,
    InvalidPageIdError,
    InvalidSlotIdError,
    PageNotFoundError,
    PageSizeError,
    RecordNotFoundError,
    RecordSizeError,
    SlottedPageCorruptionError,
    StorageClosedError,
    StorageCorruptionError,
    StorageError,
)
from strata_engine.storage.page import PAGE_SIZE, Page
from strata_engine.storage.page_file import PageFile
from strata_engine.storage.page_id import PageId, validate_page_id
from strata_engine.storage.record_id import RecordId
from strata_engine.storage.slotted_page import SlottedPage

__all__ = [
    "PAGE_SIZE",
    "Page",
    "PageId",
    "validate_page_id",
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
