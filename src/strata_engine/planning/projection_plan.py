"""Plan for selecting and ordering columns from a child plan."""

from typing import Sequence

from strata_engine.execution import Projection
from strata_engine.execution.projection import MAX_PROJECTION_COLUMNS, MIN_PROJECTION_COLUMNS
from strata_engine.planning.plan import Plan
from strata_engine.schema import DuplicateColumnError, Schema


class ProjectionPlan(Plan):
    """Immutable plan with an eagerly derived output schema."""

    __slots__ = ("_child", "_columns", "_schema")

    def __init__(self, child: Plan, columns: Sequence[str]) -> None:
        if not isinstance(child, Plan):
            raise TypeError(f"Expected Plan instance for child, got {type(child).__name__}.")
        if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes)):
            raise TypeError(f"Expected sequence of column names, got {type(columns).__name__}.")

        names = tuple(columns)
        count = len(names)
        if not (MIN_PROJECTION_COLUMNS <= count <= MAX_PROJECTION_COLUMNS):
            raise ValueError(
                f"Projection must contain between {MIN_PROJECTION_COLUMNS} and "
                f"{MAX_PROJECTION_COLUMNS} columns, got {count}."
            )

        seen_names: set[str] = set()
        resolved_columns = []
        for name in names:
            if not isinstance(name, str):
                raise TypeError(
                    f"Projected column name must be str, got {type(name).__name__}."
                )
            if name.lower() in seen_names:
                raise DuplicateColumnError(
                    f"Duplicate projected column name '{name}' "
                    "(matches case-insensitively)."
                )
            seen_names.add(name.lower())
            resolved_columns.append(child.schema.get_column_by_name(name))

        self._child = child
        self._columns = names
        self._schema = Schema(resolved_columns)
        self._freeze()

    @property
    def child(self) -> Plan:
        """Return the logical child plan."""
        return self._child

    @property
    def columns(self) -> tuple[str, ...]:
        """Return the immutable requested projection names."""
        return self._columns

    @property
    def schema(self) -> Schema:
        """Return the eagerly derived output schema."""
        return self._schema

    def create_operator(self) -> Projection:
        """Create a fresh Projection and fresh descendant operator tree."""
        return Projection(self._child.create_operator(), self._columns)
