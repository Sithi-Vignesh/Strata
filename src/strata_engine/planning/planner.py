"""Deterministic construction of plans from resolved query requests."""

from strata_engine.planning.filter_plan import FilterPlan
from strata_engine.planning.aggregate_plan import AggregatePlan
from strata_engine.planning.limit_plan import LimitPlan
from strata_engine.planning.plan import Plan
from strata_engine.planning.projection_plan import ProjectionPlan
from strata_engine.planning.sort_plan import SortPlan
from strata_engine.planning.query_request import QueryRequest
from strata_engine.planning.table_scan_plan import TableScanPlan
from strata_engine.planning.join_plan import JoinPlan
from strata_engine.planning.join_projection_plan import JoinProjectionPlan
from strata_engine.planning.join import AndCondition, ColumnLiteralCondition, IsNullCondition, NotCondition, OrCondition
from strata_engine.execution import AndPredicate, ComparisonPredicate, IsNullPredicate, NotPredicate, OrPredicate
from strata_engine.planning.order_by import OrderBy
from strata_engine.planning.aggregate import AggregateSpec
from strata_engine.planning.column_ref import ColumnRef


class Planner:
    """Create the fixed non-optimizing plan shapes supported by Phase 7."""

    def plan(self, request: QueryRequest) -> Plan:
        """Build a scan, optional filter, and optional projection plan tree."""
        if not isinstance(request, QueryRequest):
            raise TypeError(f"Expected QueryRequest instance, got {type(request).__name__}.")

        plan: Plan = TableScanPlan(request.table)
        if request.join is not None:
            right = TableScanPlan(request.join.right_table)
            plan = JoinPlan(plan, right, request.join.condition, request.table.name, request.join.right_table.name)
            layout = plan.layout
            if request.joined_where is not None:
                plan = FilterPlan(plan, _resolve_joined_where(request.joined_where, layout))
            if request.aggregates is not None:
                aggregates = tuple(
                    AggregateSpec(
                        spec.operation,
                        None if spec.column_name is None else _resolve_join_aggregate_column(spec.column_name, layout),
                        spec.output_name,
                    )
                    for spec in request.aggregates
                )
                groups = (
                    tuple(_resolve_join_aggregate_column(ref, layout) for ref in request.group_by)
                    if request.group_by is not None
                    else None
                )
                group_output_names = (
                    tuple(layout.resolve(ref).column.name for ref in request.group_by)
                    if request.group_by is not None
                    else None
                )
                plan = AggregatePlan(
                    plan, aggregates, groups, request.aggregate_output, group_output_names
                )
                if request.group_by is not None and request.order_by is not None:
                    plan = SortPlan(plan, request.order_by)
                if request.limit is not None:
                    plan = LimitPlan(plan, request.limit, request.offset)
                return plan
            if request.join_order_by is not None:
                plan = SortPlan(plan, tuple(OrderBy(layout.resolve(item.column).internal_name, item.descending) for item in request.join_order_by))
            plan = JoinProjectionPlan(plan, tuple(layout.resolve(item) for item in request.join_projection))
            if request.limit is not None: plan = LimitPlan(plan, request.limit, request.offset)
            return plan
        if request.predicate is not None:
            plan = FilterPlan(plan, request.predicate)
        if request.aggregates is not None:
            plan = AggregatePlan(plan, request.aggregates, request.group_by, request.aggregate_output)
            if request.group_by is not None and request.order_by is not None:
                plan = SortPlan(plan, request.order_by)
            if request.limit is not None:
                plan = LimitPlan(plan, request.limit, request.offset)
            return plan
        if request.order_by is not None:
            plan = SortPlan(plan, request.order_by)
        if request.projection is not None:
            plan = ProjectionPlan(plan, request.projection)
        if request.limit is not None:
            plan = LimitPlan(plan, request.limit, request.offset)
        return plan

def _resolve_joined_where(condition: object, layout):
    if isinstance(condition, ColumnLiteralCondition):
        return ComparisonPredicate(layout.resolve(condition.column).internal_name, condition.operator, condition.value)
    if isinstance(condition, IsNullCondition):
        return IsNullPredicate(layout.resolve(condition.column).internal_name, condition.is_not_null)
    if isinstance(condition, AndCondition): return AndPredicate(_resolve_joined_where(condition.left, layout), _resolve_joined_where(condition.right, layout))
    if isinstance(condition, OrCondition): return OrPredicate(_resolve_joined_where(condition.left, layout), _resolve_joined_where(condition.right, layout))
    if isinstance(condition, NotCondition): return NotPredicate(_resolve_joined_where(condition.child, layout))
    raise TypeError("Unsupported joined WHERE condition.")


def _resolve_join_aggregate_column(column: str | ColumnRef, layout) -> str:
    if isinstance(column, str):
        column = ColumnRef(column)
    return layout.resolve(column).internal_name
