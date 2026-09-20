"""Exceptions for the Strata execution engine and operator lifecycle."""

from strata_engine.exceptions import StrataError


class ExecutionError(StrataError):
    """Base exception for all execution and operator errors."""


class OperatorClosedError(ExecutionError):
    """Raised when an operation is attempted on an uninitialized or closed Operator."""
