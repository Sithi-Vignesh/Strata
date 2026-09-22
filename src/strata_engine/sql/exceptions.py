"""Exceptions raised by the minimal Strata SQL frontend."""

from strata_engine.exceptions import StrataError


class SQLError(StrataError):
    """Base exception for SQL frontend failures."""


class SQLLexError(SQLError):
    """Raised when SQL text cannot be tokenized."""


class SQLParseError(SQLError):
    """Raised when a token stream does not match the supported SQL grammar."""


class SQLBindingError(SQLError):
    """Raised for binder invariants not covered by a more specific engine error."""
