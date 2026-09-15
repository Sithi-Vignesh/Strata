"""Strata Storage Engine Package.

Provides fixed-size pages, validated page identifiers, and a disk-backed
page file manager for low-level block storage.
"""

from strata_engine.storage.exceptions import (
    InvalidPageIdError,
    PageNotFoundError,
    PageSizeError,
    StorageClosedError,
    StorageCorruptionError,
    StorageError,
)
from strata_engine.storage.page import PAGE_SIZE, Page
from strata_engine.storage.page_file import PageFile
from strata_engine.storage.page_id import PageId, validate_page_id

__all__ = [
    "PAGE_SIZE",
    "Page",
    "PageId",
    "validate_page_id",
    "PageFile",
    "StorageError",
    "PageSizeError",
    "InvalidPageIdError",
    "PageNotFoundError",
    "StorageClosedError",
    "StorageCorruptionError",
]
