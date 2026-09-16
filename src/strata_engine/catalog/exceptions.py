"""Exceptions for the Strata System Catalog and Table subsystems."""

from strata_engine.exceptions import StrataError


class CatalogError(StrataError):
    """Base exception for all system catalog and metadata errors."""


class CatalogCorruptionError(CatalogError):
    """Raised when catalog files, metadata headers, or descriptors violate integrity invariants."""


class TableNotFoundError(CatalogError):
    """Raised when attempting to access a table that does not exist in the catalog."""


class TableAlreadyExistsError(CatalogError):
    """Raised when attempting to create a table with a name that already exists."""


class ReservedNameError(CatalogError):
    """Raised when attempting to create a user table with a reserved system name."""
