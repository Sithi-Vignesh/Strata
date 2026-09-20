"""Strata execution engine package.

Provides Volcano-style execution operators, predicates, and lifecycle management.
"""

from strata_engine.execution.exceptions import (
    ExecutionError,
    OperatorClosedError,
)
from strata_engine.execution.filter import Filter
from strata_engine.execution.operator import Operator
from strata_engine.execution.predicate import (
    ComparisonPredicate,
    IsNullPredicate,
    Predicate,
)
from strata_engine.execution.projection import Projection
from strata_engine.execution.table_scan import TableScan

__all__ = [
    "ExecutionError",
    "OperatorClosedError",
    "Operator",
    "TableScan",
    "Predicate",
    "ComparisonPredicate",
    "IsNullPredicate",
    "Filter",
    "Projection",
]
