"""Join-only projection plan preserving user-facing output labels."""
from collections.abc import Sequence
from strata_engine.execution.join_projection import JoinProjection
from strata_engine.planning.join_plan import JoinPlan, ResolvedColumn
from strata_engine.planning.plan import Plan
from strata_engine.schema import Column, Schema

class JoinProjectionPlan(Plan):
    __slots__ = ("_child", "_indices", "_schema")
    def __init__(self, child: Plan, columns: Sequence[ResolvedColumn]) -> None:
        if not isinstance(child, Plan) or not isinstance(columns, Sequence) or not columns: raise TypeError("JoinProjectionPlan requires a child and resolved columns.")
        resolved = tuple(columns)
        names = _output_names(resolved)
        output = [Column(name, item.column.data_type, item.column.nullable, item.column.max_length) for item, name in zip(resolved, names)]
        self._child, self._indices, self._schema = child, tuple(item.index for item in resolved), Schema(output)
        self._freeze()
    @property
    def child(self): return self._child
    @property
    def schema(self): return self._schema
    def create_operator(self): return JoinProjection(self._child.create_operator(), self._indices, self._schema)

def _output_names(columns: tuple[ResolvedColumn, ...]) -> tuple[str, ...]:
    simple = [item.column.name for item in columns]
    counts = {name.lower(): sum(other.column.name.lower() == name.lower() for other in columns) for name in simple}
    names = []
    for item in columns:
        name = item.column.name
        if counts[name.lower()] > 1:
            prefix = item.qualifier[:32] + "_"
            name = prefix + name[:64-len(prefix)]
        names.append(name)
    if len({name.lower() for name in names}) != len(names): raise ValueError("Joined projection output names collide.")
    return tuple(names)
