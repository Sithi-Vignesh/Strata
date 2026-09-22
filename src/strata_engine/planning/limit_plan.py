"""Plan for limiting a child plan's output."""

from strata_engine.execution import Limit
from strata_engine.planning.plan import Plan
from strata_engine.schema import Schema


class LimitPlan(Plan):
    """Immutable plan that preserves schema while limiting child rows."""

    __slots__ = ("_child", "_limit", "_offset")

    def __init__(self, child: Plan, limit: int, offset: int = 0) -> None:
        if not isinstance(child, Plan):
            raise TypeError(f"Expected Plan instance for child, got {type(child).__name__}.")
        _validate_count("limit", limit)
        _validate_count("offset", offset)
        self._child = child
        self._limit = limit
        self._offset = offset
        self._freeze()

    @property
    def child(self) -> Plan:
        return self._child

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def schema(self) -> Schema:
        return self._child.schema

    def create_operator(self) -> Limit:
        return Limit(self._child.create_operator(), self._limit, self._offset)


def _validate_count(name: str, value: int) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an int, got {type(value).__name__}.")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}.")
