"""Public materialized result values returned by the engine facade."""

from dataclasses import dataclass

from strata_engine.schema import Schema, Tuple


@dataclass(frozen=True, slots=True)
class QueryResult:
    """An immutable, fully materialized relational query result."""

    schema: Schema
    rows: tuple[Tuple, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(self.schema).__name__}.")
        if not isinstance(self.rows, tuple):
            raise TypeError(f"Expected tuple of Tuple rows, got {type(self.rows).__name__}.")
        for row in self.rows:
            if not isinstance(row, Tuple):
                raise TypeError(f"QueryResult rows must be Tuple instances, got {type(row).__name__}.")
            if row.schema != self.schema:
                raise ValueError("QueryResult row schema must match the result schema.")


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Immutable metadata returned by a successfully executed SQL command."""

    affected_rows: int

    def __post_init__(self) -> None:
        if type(self.affected_rows) is not int or self.affected_rows < 0:
            raise ValueError("affected_rows must be a non-negative int.")


@dataclass(frozen=True, slots=True)
class IndexCondition:
    """Resolved index comparison metadata for one profiled query."""

    column_name: str
    operator: str
    literal: object

    def __post_init__(self) -> None:
        if not isinstance(self.column_name, str):
            raise TypeError(f"column_name must be a str, got {type(self.column_name).__name__}.")
        if self.operator not in {"=", "<", "<=", ">", ">="}:
            raise ValueError(f"Unsupported index condition operator '{self.operator}'.")


@dataclass(frozen=True, slots=True)
class TableScanMetrics:
    """Observed work performed by one TableScan execution."""

    tuples_examined: int

    def __post_init__(self) -> None:
        _validate_metric("tuples_examined", self.tuples_examined)


@dataclass(frozen=True, slots=True)
class IndexScanMetrics:
    """Observed B+ tree and heap work performed by one IndexScan execution."""

    tree_pages_visited: int
    leaf_entries_examined: int
    rids_selected: int
    rows_fetched: int

    def __post_init__(self) -> None:
        _validate_metric("tree_pages_visited", self.tree_pages_visited)
        _validate_metric("leaf_entries_examined", self.leaf_entries_examined)
        _validate_metric("rids_selected", self.rids_selected)
        _validate_metric("rows_fetched", self.rows_fetched)


@dataclass(frozen=True, slots=True)
class QueryProfile:
    """Immutable access-path metadata and observed scan metrics for one query."""

    access_path: str
    table_name: str
    index_name: str | None
    condition: IndexCondition | None
    metrics: TableScanMetrics | IndexScanMetrics

    def __post_init__(self) -> None:
        if self.access_path not in {"TableScan", "IndexScan"}:
            raise ValueError(f"Unsupported access path '{self.access_path}'.")
        if not isinstance(self.table_name, str):
            raise TypeError(f"table_name must be a str, got {type(self.table_name).__name__}.")
        if self.index_name is not None and not isinstance(self.index_name, str):
            raise TypeError(f"index_name must be a str or None, got {type(self.index_name).__name__}.")
        if self.access_path == "TableScan":
            if self.index_name is not None or self.condition is not None:
                raise ValueError("TableScan profiles must not include index metadata.")
            if not isinstance(self.metrics, TableScanMetrics):
                raise TypeError("TableScan profiles require TableScanMetrics.")
        else:
            if self.index_name is None or not isinstance(self.condition, IndexCondition):
                raise ValueError("IndexScan profiles require index metadata and a condition.")
            if not isinstance(self.metrics, IndexScanMetrics):
                raise TypeError("IndexScan profiles require IndexScanMetrics.")


@dataclass(frozen=True, slots=True)
class ProfiledExecutionResult:
    """Normal execution output with an optional single-table scan profile."""

    result: QueryResult | CommandResult
    profile: QueryProfile | None

    def __post_init__(self) -> None:
        if not isinstance(self.result, (QueryResult, CommandResult)):
            raise TypeError(
                "result must be a QueryResult or CommandResult, "
                f"got {type(self.result).__name__}."
            )
        if self.profile is not None and not isinstance(self.profile, QueryProfile):
            raise TypeError(
                f"profile must be a QueryProfile or None, got {type(self.profile).__name__}."
            )


def _validate_metric(name: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int.")
