"""Exceptions specific to query planning."""

from strata_engine.exceptions import StrataError


class PlanningError(StrataError):
    """Raised for planning-specific failures."""
