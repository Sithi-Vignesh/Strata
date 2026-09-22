"""Immutable unresolved syntax tree nodes for the supported SQL subset."""

from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class SelectAll:
    """The explicit SQL ``*`` projection."""


@dataclass(frozen=True, slots=True)
class ColumnList:
    """An explicit, ordered SQL projection."""

    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.columns, Sequence) or isinstance(self.columns, (str, bytes)):
            raise TypeError(
                f"Expected sequence of column names, got {type(self.columns).__name__}."
            )
        if not all(isinstance(column, str) for column in self.columns):
            raise TypeError("Column names must all be strings.")
        object.__setattr__(self, "columns", tuple(self.columns))


class SQLPredicate:
    """Marker base class for supported WHERE predicate forms."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class ComparisonExpression(SQLPredicate):
    """An unresolved column-to-literal comparison."""

    column_name: str
    operator: str
    value: object


@dataclass(frozen=True, slots=True)
class IsNullExpression(SQLPredicate):
    """An unresolved ``IS [NOT] NULL`` condition."""

    column_name: str
    is_not_null: bool = False


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
class SelectStatement:
    """One unresolved single-table SELECT statement."""

    table_name: str
    projection: SelectAll | ColumnList
    where: SQLPredicate | None
