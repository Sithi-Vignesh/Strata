"""Plan for sorting a child plan by resolved source columns."""

from collections.abc import Sequence

from strata_engine.execution import Sort
from strata_engine.execution.sort import SortKey
from strata_engine.planning.order_by import OrderBy
from strata_engine.planning.plan import Plan
from strata_engine.schema import DuplicateColumnError, Schema


class SortPlan(Plan):
    """Immutable plan that preserves schema while ordering child rows."""

    __slots__ = ("_child", "_order_by", "_sort_keys")

    def __init__(self, child: Plan, order_by: Sequence[OrderBy]) -> None:
        if not isinstance(child, Plan):
            raise TypeError(f"Expected Plan instance for child, got {type(child).__name__}.")
        if not isinstance(order_by, Sequence) or isinstance(order_by, (str, bytes)):
            raise TypeError(f"Expected sequence of OrderBy objects, got {type(order_by).__name__}.")
        items = tuple(order_by)
        if not items:
            raise ValueError("SortPlan requires at least one ordering item.")
        if not all(isinstance(item, OrderBy) for item in items):
            raise TypeError("SortPlan ordering items must all be OrderBy instances.")

        seen: set[str] = set()
        sort_keys: list[SortKey] = []
        for item in items:
            normalized = item.column_name.lower()
            if normalized in seen:
                raise DuplicateColumnError(
                    f"Duplicate ordering column name '{item.column_name}' (matches case-insensitively)."
                )
            seen.add(normalized)
            sort_keys.append(SortKey(child.schema.column_index(item.column_name), item.descending))

        self._child = child
        self._order_by = items
        self._sort_keys = tuple(sort_keys)
        self._freeze()

    @property
    def child(self) -> Plan:
        return self._child

    @property
    def order_by(self) -> tuple[OrderBy, ...]:
        return self._order_by

    @property
    def schema(self) -> Schema:
        return self._child.schema

    def create_operator(self) -> Sort:
        return Sort(self._child.create_operator(), self._sort_keys)
