"""Deterministic construction of plans from resolved query requests."""

from strata_engine.planning.filter_plan import FilterPlan
from strata_engine.planning.limit_plan import LimitPlan
from strata_engine.planning.plan import Plan
from strata_engine.planning.projection_plan import ProjectionPlan
from strata_engine.planning.sort_plan import SortPlan
from strata_engine.planning.query_request import QueryRequest
from strata_engine.planning.table_scan_plan import TableScanPlan


class Planner:
    """Create the fixed non-optimizing plan shapes supported by Phase 7."""

    def plan(self, request: QueryRequest) -> Plan:
        """Build a scan, optional filter, and optional projection plan tree."""
        if not isinstance(request, QueryRequest):
            raise TypeError(f"Expected QueryRequest instance, got {type(request).__name__}.")

        plan: Plan = TableScanPlan(request.table)
        if request.predicate is not None:
            plan = FilterPlan(plan, request.predicate)
        if request.order_by is not None:
            plan = SortPlan(plan, request.order_by)
        if request.projection is not None:
            plan = ProjectionPlan(plan, request.projection)
        if request.limit is not None:
            plan = LimitPlan(plan, request.limit, request.offset)
        return plan
