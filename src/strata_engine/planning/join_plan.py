"""Binary join plan and its shared logical joined-column layout."""
from dataclasses import dataclass
from strata_engine.execution.nested_loop_join import JoinKey, NestedLoopJoin
from strata_engine.planning.column_ref import ColumnRef
from strata_engine.planning.join import AmbiguousColumnError, JoinCondition
from strata_engine.planning.plan import Plan
from strata_engine.schema import Column, ColumnNotFoundError, Schema, TypeMismatchError

@dataclass(frozen=True, slots=True)
class ResolvedColumn:
    index: int
    internal_name: str
    column: Column
    qualifier: str

class JoinedLayout:
    __slots__ = ("_left_name", "_right_name", "_left_schema", "_right_schema", "_schema", "_left", "_right")
    def __init__(self, left_name: str, right_name: str, left_schema: Schema, right_schema: Schema) -> None:
        self._left_name, self._right_name = left_name, right_name
        self._left_schema, self._right_schema = left_schema, right_schema
        columns = []; left = {}; right = {}
        for i, col in enumerate(left_schema.columns):
            name = f"_j_left_{i}"; columns.append(Column(name, col.data_type, col.nullable, col.max_length)); left[col.name.lower()] = ResolvedColumn(i, name, col, left_name)
        base = len(left_schema)
        for i, col in enumerate(right_schema.columns):
            name = f"_j_right_{i}"; columns.append(Column(name, col.data_type, col.nullable, col.max_length)); right[col.name.lower()] = ResolvedColumn(base + i, name, col, right_name)
        self._schema, self._left, self._right = Schema(columns), left, right
    @property
    def schema(self) -> Schema: return self._schema
    def resolve(self, ref: ColumnRef) -> ResolvedColumn:
        name = ref.column_name.lower()
        if ref.qualifier is not None:
            qualifier = ref.qualifier.lower()
            if qualifier == self._left_name.lower(): mapping = self._left
            elif qualifier == self._right_name.lower(): mapping = self._right
            else: raise ColumnNotFoundError(f"Unknown table qualifier '{ref.qualifier}'.")
            if name not in mapping: raise ColumnNotFoundError(f"Column '{ref.column_name}' not found for '{ref.qualifier}'.")
            return mapping[name]
        matches = [mapping[name] for mapping in (self._left, self._right) if name in mapping]
        if not matches: raise ColumnNotFoundError(f"Column '{ref.column_name}' not found in joined sources.")
        if len(matches) > 1: raise AmbiguousColumnError(f"Column '{ref.column_name}' is ambiguous in joined sources.")
        return matches[0]

class JoinPlan(Plan):
    __slots__ = ("_left", "_right", "_condition", "_layout", "_key")
    def __init__(self, left: Plan, right: Plan, condition: JoinCondition, left_name: str, right_name: str) -> None:
        if not isinstance(left, Plan) or not isinstance(right, Plan): raise TypeError("JoinPlan children must be Plans.")
        if not isinstance(condition, JoinCondition): raise TypeError("condition must be a JoinCondition.")
        if left_name.lower() == right_name.lower(): raise ValueError("Join sources must be distinct.")
        layout = JoinedLayout(left_name, right_name, left.schema, right.schema)
        first, second = layout.resolve(condition.left), layout.resolve(condition.right)
        left_count = left.schema.column_count
        first_left, second_left = first.index < left_count, second.index < left_count
        if first_left == second_left: raise ValueError("JOIN ON must reference one column from each source.")
        left_col, right_col = (first, second) if first_left else (second, first)
        if left_col.column.data_type != right_col.column.data_type:
            raise TypeMismatchError(f"JOIN equality requires identical DataTypes, got {left_col.column.data_type.value} and {right_col.column.data_type.value}.")
        self._left, self._right, self._condition, self._layout = left, right, condition, layout
        self._key = JoinKey(left_col.index, right_col.index - left_count)
        self._freeze()
    @property
    def left(self): return self._left
    @property
    def right(self): return self._right
    @property
    def layout(self): return self._layout
    @property
    def schema(self): return self._layout.schema
    def create_operator(self): return NestedLoopJoin(self._left.create_operator(), self._right.create_operator(), self._key, self.schema)
