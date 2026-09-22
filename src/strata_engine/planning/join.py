"""Immutable join request and joined-WHERE planning representations."""
from dataclasses import dataclass
from strata_engine.catalog import Table
from strata_engine.planning.column_ref import ColumnRef
from strata_engine.planning.exceptions import AmbiguousColumnError

@dataclass(frozen=True, slots=True)
class JoinCondition:
    left: ColumnRef
    right: ColumnRef

@dataclass(frozen=True, slots=True)
class JoinSpec:
    right_table: Table
    condition: JoinCondition

    def __post_init__(self) -> None:
        if not isinstance(self.right_table, Table):
            raise TypeError("right_table must be a Table.")
        if not isinstance(self.condition, JoinCondition):
            raise TypeError("condition must be a JoinCondition.")

@dataclass(frozen=True, slots=True)
class JoinOrderBy:
    column: ColumnRef
    descending: bool = False

@dataclass(frozen=True, slots=True)
class ColumnLiteralCondition:
    column: ColumnRef
    operator: str
    value: object

@dataclass(frozen=True, slots=True)
class IsNullCondition:
    column: ColumnRef
    is_not_null: bool = False

@dataclass(frozen=True, slots=True)
class AndCondition:
    left: object
    right: object

@dataclass(frozen=True, slots=True)
class OrCondition:
    left: object
    right: object

@dataclass(frozen=True, slots=True)
class NotCondition:
    child: object
