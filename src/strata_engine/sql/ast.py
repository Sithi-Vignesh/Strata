"""Immutable unresolved syntax tree nodes for the supported SQL subset."""

from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class SelectAll:
    """The explicit SQL ``*`` projection."""

@dataclass(frozen=True, slots=True)
class QualifiedIdentifier:
    column_name: str
    qualifier: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnList:
    """An explicit, ordered SQL projection."""

    columns: tuple[str | QualifiedIdentifier, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.columns, Sequence) or isinstance(self.columns, (str, bytes)):
            raise TypeError(
                f"Expected sequence of column names, got {type(self.columns).__name__}."
            )
        if not all(isinstance(column, (str, QualifiedIdentifier)) for column in self.columns):
            raise TypeError("Column names must all be strings or QualifiedIdentifier values.")
        object.__setattr__(self, "columns", tuple(self.columns))


@dataclass(frozen=True, slots=True)
class AggregateCall:
    """An unresolved global aggregate call; ``None`` argument denotes ``COUNT(*)``."""

    function_name: str
    argument_name: str | None = None


@dataclass(frozen=True, slots=True)
class AggregateList:
    """An ordered aggregate-only SELECT list."""

    aggregates: tuple[AggregateCall, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.aggregates, Sequence) or isinstance(self.aggregates, (str, bytes)):
            raise TypeError("Expected sequence of AggregateCall objects.")
        if not self.aggregates or not all(isinstance(item, AggregateCall) for item in self.aggregates):
            raise TypeError("AggregateList requires one or more AggregateCall objects.")
        object.__setattr__(self, "aggregates", tuple(self.aggregates))


class SQLPredicate:
    """Marker base class for supported WHERE predicate forms."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class ComparisonExpression(SQLPredicate):
    """An unresolved column-to-literal comparison."""

    column_name: str
    operator: str
    value: object
    qualifier: str | None = None


@dataclass(frozen=True, slots=True)
class IsNullExpression(SQLPredicate):
    """An unresolved ``IS [NOT] NULL`` condition."""

    column_name: str
    is_not_null: bool = False
    qualifier: str | None = None


@dataclass(frozen=True, slots=True)
class AndExpression(SQLPredicate):
    """An unresolved Boolean conjunction."""

    left: SQLPredicate
    right: SQLPredicate


@dataclass(frozen=True, slots=True)
class OrExpression(SQLPredicate):
    """An unresolved Boolean disjunction."""

    left: SQLPredicate
    right: SQLPredicate


@dataclass(frozen=True, slots=True)
class NotExpression(SQLPredicate):
    """An unresolved Boolean negation."""

    child: SQLPredicate


@dataclass(frozen=True, slots=True)
class OrderByItem:
    """One unresolved SQL ORDER BY item."""

    column_name: str
    descending: bool = False
    qualifier: str | None = None

@dataclass(frozen=True, slots=True)
class JoinClause:
    right_table_name: str
    left_column: QualifiedIdentifier
    right_column: QualifiedIdentifier


@dataclass(frozen=True, slots=True)
class SelectStatement:
    """One unresolved single-table SELECT statement."""

    table_name: str
    projection: SelectAll | ColumnList | AggregateList
    where: SQLPredicate | None
    order_by: tuple[OrderByItem, ...] | None = None
    limit: int | None = None
    offset: int = 0
    join: JoinClause | None = None
