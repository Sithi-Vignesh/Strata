"""Binding from unresolved SQL syntax to existing Strata query requests."""

from strata_engine.catalog import Catalog
from strata_engine.execution import ComparisonPredicate, IsNullPredicate, Predicate
from strata_engine.planning import QueryRequest
from strata_engine.sql.ast import (
    ColumnList,
    ComparisonExpression,
    IsNullExpression,
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

        predicate: Predicate | None = None
        if isinstance(statement.where, ComparisonExpression):
            predicate = ComparisonPredicate(
                statement.where.column_name,
                statement.where.operator,
                statement.where.value,
            )
        elif isinstance(statement.where, IsNullExpression):
            predicate = IsNullPredicate(
                statement.where.column_name,
                is_not_null=statement.where.is_not_null,
            )
        elif statement.where is not None:
            raise SQLBindingError("Unsupported SQL predicate node.")

        return QueryRequest(table=table, predicate=predicate, projection=projection)
