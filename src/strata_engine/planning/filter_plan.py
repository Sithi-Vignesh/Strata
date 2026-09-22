"""Plan for filtering a child plan with an existing predicate."""

from strata_engine.execution import Filter, Predicate
from strata_engine.planning.plan import Plan
from strata_engine.schema import Schema


class FilterPlan(Plan):
    """Immutable plan that preserves its child schema while applying a predicate."""

    __slots__ = ("_child", "_predicate")

    def __init__(self, child: Plan, predicate: Predicate) -> None:
        if not isinstance(child, Plan):
            raise TypeError(f"Expected Plan instance for child, got {type(child).__name__}.")
        if not isinstance(predicate, Predicate):
            raise TypeError(
                f"Expected Predicate instance for predicate, got {type(predicate).__name__}."
            )

        predicate.validate(child.schema)
        self._child = child
        self._predicate = predicate
        self._freeze()

    @property
    def child(self) -> Plan:
        """Return the logical child plan."""
        return self._child

    @property
    def predicate(self) -> Predicate:
        """Return the validated predicate."""
        return self._predicate

    @property
    def schema(self) -> Schema:
        """Return exactly the child schema."""
        return self._child.schema

    def create_operator(self) -> Filter:
        """Create a fresh Filter and fresh descendant operator tree."""
        return Filter(self._child.create_operator(), self._predicate)
