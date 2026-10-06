"""Strata Catalog and Table management subsystem.

Provides Table and Catalog for managing persistent table definitions,
schema metadata, and table lifecycles.
"""

from strata_engine.catalog.catalog import Catalog
from strata_engine.catalog.exceptions import (
    CatalogCorruptionError,
    CatalogError,
    IndexAlreadyExistsError,
    ReservedNameError,
    TableAlreadyExistsError,
    TableNotFoundError,
    UnsupportedIndexTypeError,
)
from strata_engine.catalog.table import Table
from strata_engine.catalog.index import IndexMetadata, TableIndex

__all__ = [
    "Catalog",
    "Table",
    "CatalogError",
    "CatalogCorruptionError",
    "TableNotFoundError",
    "TableAlreadyExistsError",
    "ReservedNameError",
    "IndexAlreadyExistsError",
    "UnsupportedIndexTypeError",
    "IndexMetadata",
    "TableIndex",
]
