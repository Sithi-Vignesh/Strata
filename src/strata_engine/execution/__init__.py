"""Strata execution engine package.

Provides Volcano-style execution operators, predicates, and lifecycle management.
"""

from strata_engine.execution.exceptions import (
    ExecutionError,
    OperatorClosedError,
)
from strata_engine.execution.filter import Filter
from strata_engine.execution.aggregate import Aggregate
from strata_engine.execution.limit import Limit
from strata_engine.execution.operator import Operator
from strata_engine.execution.predicate import (
    AndPredicate,
    ComparisonPredicate,
    IsNullPredicate,
    NotPredicate,
    OrPredicate,
    Predicate,
)
from strata_engine.execution.projection import Projection
from strata_engine.execution.sort import Sort
from strata_engine.execution.table_scan import TableScan

__all__ = [
    "ExecutionError",
    "OperatorClosedError",
    "Operator",
    "TableScan",
    "Predicate",
    "ComparisonPredicate",
    "IsNullPredicate",
    "AndPredicate",
    "OrPredicate",
    "NotPredicate",
    "Filter",
    "Aggregate",
    "Projection",
    "Sort",
    "Limit",
]
