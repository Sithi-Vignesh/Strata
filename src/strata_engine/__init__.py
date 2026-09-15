"""Strata Engine Package.

Provides the custom relational database engine for the Strata system.
"""

from strata_engine.engine import StrataEngine
from strata_engine.storage import (
    PAGE_SIZE,
    InvalidPageIdError,
    Page,
    PageFile,
    PageId,
    PageNotFoundError,
    PageSizeError,
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
    "StorageError",
    "PageSizeError",
    "InvalidPageIdError",
    "PageNotFoundError",
    "StorageClosedError",
    "StorageCorruptionError",
]
