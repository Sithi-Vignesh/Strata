"""Exceptions specific to query planning."""

from strata_engine.exceptions import StrataError


class PlanningError(StrataError):
    """Raised for planning-specific failures."""


class AmbiguousColumnError(PlanningError):
    """Raised when an unqualified joined column reference is ambiguous."""
