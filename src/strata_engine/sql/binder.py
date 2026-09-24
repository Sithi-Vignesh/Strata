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
from strata_engine.planning import OrderBy, QueryRequest
from strata_engine.planning import AggregateOutputSpec, AggregateSpec
from strata_engine.planning import ColumnRef, JoinCondition, JoinOrderBy, JoinSpec
from strata_engine.planning.join import AndCondition, ColumnLiteralCondition, IsNullCondition, NotCondition, OrCondition
from strata_engine.sql.ast import (
    AndExpression,
    AggregateCall,
    AggregateList,
    GroupedAggregateList,
    QualifiedIdentifier,
    ColumnList,
    ComparisonExpression,
    IsNullExpression,
    NotExpression,
    OrExpression,
    OrderByItem,
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
        if statement.join is not None:
            return self._bind_join(statement, table)
        if statement.group_by is not None:
            return self._bind_grouped(statement, table)
        if isinstance(statement.projection, SelectAll):
            projection: tuple[str, ...] | None = None
            aggregates = None
        elif isinstance(statement.projection, ColumnList):
            if any(isinstance(item, QualifiedIdentifier) for item in statement.projection.columns):
                raise SQLBindingError("Qualified column references require a JOIN.")
            projection = statement.projection.columns
            aggregates = None
        elif isinstance(statement.projection, AggregateList):
            if any(isinstance(item.argument_name, QualifiedIdentifier) for item in statement.projection.aggregates):
                raise SQLBindingError("Qualified aggregate references require a JOIN.")
            projection = None
            aggregates = tuple(
                AggregateSpec(item.function_name, item.argument_name)
                for item in statement.projection.aggregates
            )
        else:
            raise SQLBindingError("Unsupported SQL projection node.")

        if aggregates is not None and statement.order_by is not None:
            raise SQLBindingError("ORDER BY is not supported for aggregate queries.")
        if statement.order_by is not None and any(item.qualifier is not None for item in statement.order_by):
            raise SQLBindingError("Qualified ORDER BY references require a JOIN.")
        if statement.where is not None and _has_qualified_predicate(statement.where):
            raise SQLBindingError("Qualified WHERE references require a JOIN.")

        predicate = self._bind_predicate(statement.where) if statement.where is not None else None
        order_by = (
            tuple(OrderBy(item.column_name, item.descending) for item in statement.order_by)
            if statement.order_by is not None
            else None
        )

        return QueryRequest(
            table=table,
            predicate=predicate,
            projection=projection,
            order_by=order_by,
            limit=statement.limit,
            offset=statement.offset,
            aggregates=aggregates,
        )

    def _bind_grouped(self, statement: SelectStatement, table) -> QueryRequest:
        if any(ref.qualifier is not None for ref in statement.group_by or ()):
            raise SQLBindingError("Qualified GROUP BY references require a JOIN.")
        group_by = tuple(ref.column_name for ref in statement.group_by or ())
        seen: set[str] = set()
        for name in group_by:
            if name.lower() in seen:
                raise SQLBindingError(f"Duplicate GROUP BY column '{name}' (matches case-insensitively).")
            seen.add(name.lower())

        if isinstance(statement.projection, AggregateList):
            items: tuple[object, ...] = statement.projection.aggregates
        elif isinstance(statement.projection, GroupedAggregateList):
            items = statement.projection.items
        else:
            raise SQLBindingError("GROUP BY requires an aggregate SELECT list.")

        aggregates: list[AggregateSpec] = []
        output: list[AggregateOutputSpec] = []
        for item in items:
            if isinstance(item, AggregateCall):
                if isinstance(item.argument_name, QualifiedIdentifier):
                    raise SQLBindingError("Qualified aggregate references require a JOIN.")
                output.append(AggregateOutputSpec("AGGREGATE", len(aggregates)))
                aggregates.append(AggregateSpec(item.function_name, item.argument_name))
            else:
                if isinstance(item, QualifiedIdentifier):
                    raise SQLBindingError("Qualified column references require a JOIN.")
                assert isinstance(item, str)
                if item.lower() not in seen:
                    raise SQLBindingError(f"Selected column '{item}' must appear in GROUP BY.")
                output.append(AggregateOutputSpec("GROUP", _group_index(group_by, item)))

        if statement.order_by is not None and any(item.qualifier is not None for item in statement.order_by):
            raise SQLBindingError("Qualified ORDER BY references require a JOIN.")
        if statement.where is not None and _has_qualified_predicate(statement.where):
            raise SQLBindingError("Qualified WHERE references require a JOIN.")
        predicate = self._bind_predicate(statement.where) if statement.where is not None else None
        order_by = tuple(OrderBy(item.column_name, item.descending) for item in statement.order_by) if statement.order_by is not None else None
        return QueryRequest(table=table, predicate=predicate, order_by=order_by, limit=statement.limit,
                            offset=statement.offset, aggregates=tuple(aggregates), group_by=group_by,
                            aggregate_output=tuple(output))

    def _bind_join(self, statement: SelectStatement, table) -> QueryRequest:
        assert statement.join is not None
        right = self._catalog.get_table(statement.join.right_table_name)
        if table.name.lower() == right.name.lower():
            raise SQLBindingError("JOIN sources must be distinct; self joins require aliases.")
        if isinstance(statement.projection, SelectAll):
            raise SQLBindingError("SELECT * is not supported for JOIN queries.")
        if statement.group_by is not None or isinstance(statement.projection, AggregateList):
            return self._bind_join_aggregate(statement, table, right)
        refs = tuple(_column_ref(item) for item in statement.projection.columns)
        condition = JoinCondition(_column_ref(statement.join.left_column), _column_ref(statement.join.right_column))
        joined_where = self._bind_joined_where(statement.where) if statement.where is not None else None
        joined_order = tuple(JoinOrderBy(ColumnRef(item.column_name, item.qualifier), item.descending) for item in statement.order_by) if statement.order_by is not None else None
        return QueryRequest(table=table, limit=statement.limit, offset=statement.offset, join=JoinSpec(right, condition), joined_where=joined_where, join_projection=refs, join_order_by=joined_order)

    def _bind_join_aggregate(self, statement: SelectStatement, table, right) -> QueryRequest:
        assert statement.join is not None
        if statement.group_by is None:
            if not isinstance(statement.projection, AggregateList):
                raise SQLBindingError("Aggregate JOIN queries require an aggregate SELECT list.")
            items: tuple[object, ...] = statement.projection.aggregates
        else:
            if isinstance(statement.projection, AggregateList):
                items = statement.projection.aggregates
            elif isinstance(statement.projection, GroupedAggregateList):
                items = statement.projection.items
            else:
                raise SQLBindingError("GROUP BY requires an aggregate SELECT list.")

        group_by = tuple(_column_ref(ref) for ref in statement.group_by or ())
        if len({_ref_key(ref) for ref in group_by}) != len(group_by):
            raise SQLBindingError("Duplicate GROUP BY column (matches case-insensitively).")

        aggregates: list[AggregateSpec] = []
        output: list[AggregateOutputSpec] = []
        for item in items:
            if isinstance(item, AggregateCall):
                argument = None if item.argument_name is None else _column_ref(item.argument_name)
                aggregates.append(
                    AggregateSpec(item.function_name, argument, _aggregate_output_name(item))
                )
                output.append(AggregateOutputSpec("AGGREGATE", len(aggregates) - 1))
            else:
                if statement.group_by is None:
                    raise SQLBindingError("Aggregate JOIN queries require an aggregate-only SELECT list.")
                ref = _column_ref(item)
                try:
                    index = next(index for index, group in enumerate(group_by) if _ref_key(group) == _ref_key(ref))
                except StopIteration as exc:
                    raise SQLBindingError(
                        f"Selected column '{ref.column_name}' must appear in GROUP BY."
                    ) from exc
                output.append(AggregateOutputSpec("GROUP", index))

        if statement.group_by is None and statement.order_by is not None:
            raise SQLBindingError("ORDER BY is not supported for aggregate queries.")
        if statement.order_by is not None and any(item.qualifier is not None for item in statement.order_by):
            raise SQLBindingError("Qualified ORDER BY is not supported after aggregation.")
        condition = JoinCondition(_column_ref(statement.join.left_column), _column_ref(statement.join.right_column))
        joined_where = self._bind_joined_where(statement.where) if statement.where is not None else None
        order_by = (
            tuple(OrderBy(item.column_name, item.descending) for item in statement.order_by)
            if statement.order_by is not None
            else None
        )
        return QueryRequest(
            table=table,
            order_by=order_by,
            limit=statement.limit,
            offset=statement.offset,
            aggregates=tuple(aggregates),
            join=JoinSpec(right, condition),
            joined_where=joined_where,
            group_by=group_by or None,
            aggregate_output=tuple(output) if group_by else None,
        )

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

    def _bind_joined_where(self, predicate: SQLPredicate) -> object:
        if isinstance(predicate, ComparisonExpression): return ColumnLiteralCondition(ColumnRef(predicate.column_name, predicate.qualifier), predicate.operator, predicate.value)
        if isinstance(predicate, IsNullExpression): return IsNullCondition(ColumnRef(predicate.column_name, predicate.qualifier), predicate.is_not_null)
        if isinstance(predicate, AndExpression): return AndCondition(self._bind_joined_where(predicate.left), self._bind_joined_where(predicate.right))
        if isinstance(predicate, OrExpression): return OrCondition(self._bind_joined_where(predicate.left), self._bind_joined_where(predicate.right))
        if isinstance(predicate, NotExpression): return NotCondition(self._bind_joined_where(predicate.child))
        raise SQLBindingError("Unsupported SQL predicate node.")

def _column_ref(value: str | QualifiedIdentifier) -> ColumnRef:
    return ColumnRef(value, None) if isinstance(value, str) else ColumnRef(value.column_name, value.qualifier)

def _has_qualified_predicate(predicate: SQLPredicate) -> bool:
    if isinstance(predicate, (ComparisonExpression, IsNullExpression)): return predicate.qualifier is not None
    if isinstance(predicate, (AndExpression, OrExpression)): return _has_qualified_predicate(predicate.left) or _has_qualified_predicate(predicate.right)
    if isinstance(predicate, NotExpression): return _has_qualified_predicate(predicate.child)
    return False


def _group_index(group_by: tuple[str, ...], name: str) -> int:
    return next(index for index, item in enumerate(group_by) if item.lower() == name.lower())


def _ref_key(ref: ColumnRef) -> tuple[str, str | None]:
    return ref.column_name.lower(), ref.qualifier.lower() if ref.qualifier is not None else None


def _aggregate_output_name(call: AggregateCall) -> str:
    if call.argument_name is None:
        return "count_star"
    argument = _column_ref(call.argument_name)
    source = argument.column_name if argument.qualifier is None else f"{argument.qualifier}_{argument.column_name}"
    prefix = call.function_name.lower() + "_"
    return prefix + source[:64 - len(prefix)]
