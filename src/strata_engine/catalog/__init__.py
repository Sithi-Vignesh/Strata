"""Strata Catalog and Table management subsystem.

Provides Table and Catalog for managing persistent table definitions,
schema metadata, and table lifecycles.
"""

from strata_engine.catalog.catalog import Catalog
from strata_engine.catalog.exceptions import (
    CatalogCorruptionError,
    CatalogError,
    ReservedNameError,
    TableAlreadyExistsError,
    TableNotFoundError,
)
from strata_engine.catalog.table import Table

__all__ = [
    "Catalog",
    "Table",
    "CatalogError",
    "CatalogCorruptionError",
    "TableNotFoundError",
    "TableAlreadyExistsError",
    "ReservedNameError",
]
