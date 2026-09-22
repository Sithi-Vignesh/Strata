"""Binding from unresolved SQL syntax to existing Strata query requests."""

from strata_engine.catalog import Catalog
from strata_engine.execution import (
    AndPredicate,
    ComparisonPredicate,
    IsNullPredicate,
    NotPredicate,
    OrPredicate,
    Predicate,
)
from strata_engine.planning import QueryRequest
from strata_engine.sql.ast import (
    AndExpression,
    ColumnList,
    ComparisonExpression,
    IsNullExpression,
    NotExpression,
    OrExpression,
    SQLPredicate,
    SelectAll,
    SelectStatement,
)
from strata_engine.sql.exceptions import SQLBindingError


class Binder:
    """Resolve SQL table names and translate syntax to existing engine abstractions."""

    def __init__(self, catalog: Catalog) -> None:
        if not isinstance(catalog, Catalog):
            raise TypeError(f"Expected Catalog instance, got {type(catalog).__name__}.")
        self._catalog = catalog

    def bind(self, statement: SelectStatement) -> QueryRequest:
        """Resolve one statement without planning, scanning, or closing borrowed resources."""
        if not isinstance(statement, SelectStatement):
            raise TypeError(f"Expected SelectStatement instance, got {type(statement).__name__}.")

        table = self._catalog.get_table(statement.table_name)
        if isinstance(statement.projection, SelectAll):
            projection: tuple[str, ...] | None = None
        elif isinstance(statement.projection, ColumnList):
            projection = statement.projection.columns
        else:
            raise SQLBindingError("Unsupported SQL projection node.")

        predicate = self._bind_predicate(statement.where) if statement.where is not None else None

        return QueryRequest(table=table, predicate=predicate, projection=projection)

    def _bind_predicate(self, predicate: SQLPredicate) -> Predicate:
        """Translate an unresolved SQL predicate tree to execution predicates."""
        if isinstance(predicate, ComparisonExpression):
            return ComparisonPredicate(predicate.column_name, predicate.operator, predicate.value)
        if isinstance(predicate, IsNullExpression):
            return IsNullPredicate(predicate.column_name, is_not_null=predicate.is_not_null)
        if isinstance(predicate, AndExpression):
            return AndPredicate(
                self._bind_predicate(predicate.left), self._bind_predicate(predicate.right)
            )
        if isinstance(predicate, OrExpression):
            return OrPredicate(
                self._bind_predicate(predicate.left), self._bind_predicate(predicate.right)
            )
        if isinstance(predicate, NotExpression):
            return NotPredicate(self._bind_predicate(predicate.child))
        raise SQLBindingError("Unsupported SQL predicate node.")
