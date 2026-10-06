"""FastAPI bridge for the DBthon SQL console."""

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from strata_backend.demo_bootstrap import bootstrap_demo
from strata_backend.engine_adapter import EngineAdapter
from strata_engine import (
    CommandResult,
    IndexScanMetrics,
    NullConstraintError,
    PlanningError,
    ProfiledExecutionResult,
    QueryResult,
    ReservedNameError,
    SchemaError,
    SQLError,
    StrataEngine,
    TableAlreadyExistsError,
    TableNotFoundError,
    TableScanMetrics,
    TupleArityError,
    TupleSizeError,
    TypeMismatchError,
    ValueOutOfRangeError,
)


logger = logging.getLogger(__name__)
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "dbthon_demo"
_CLIENT_QUERY_ERRORS = (
    SQLError,
    TableNotFoundError,
    TableAlreadyExistsError,
    SchemaError,
    PlanningError,
    TupleArityError,
    TupleSizeError,
    TypeMismatchError,
    NullConstraintError,
    ReservedNameError,
    ValueOutOfRangeError,
)


class SQLProfileRequest(BaseModel):
    """One raw SQL statement submitted by the DBthon console."""

    sql: str

    @field_validator("sql")
    @classmethod
    def sql_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sql must not be empty.")
        return value


class EngineHealthModel(BaseModel):
    """Safe engine fields exposed by the public health endpoint."""

    name: str
    status: str
    initialized: bool


class HealthResponse(BaseModel):
    """Pydantic model for the existing health endpoint."""

    status: str
    service: str
    engine: EngineHealthModel


def create_app(
    data_dir: Path | str | None = None,
    frontend_origin: str | None = None,
) -> FastAPI:
    """Create an isolated lifespan-managed Strata backend application."""
    resolved_data_dir = Path(data_dir) if data_dir is not None else _configured_data_dir()
    origin = frontend_origin or os.environ.get("STRATA_FRONTEND_ORIGIN", "http://localhost:5173")
    adapter = EngineAdapter(StrataEngine(resolved_data_dir))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        adapter.engine.open()
        try:
            bootstrap_demo(adapter.engine)
            yield
        finally:
            adapter.engine.close()

    application = FastAPI(
        title="Strata API",
        description="Collaborative project and task management backend powered by StrataEngine",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.engine_adapter = adapter
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
    def get_health(request: Request) -> HealthResponse:
        engine_status = request.app.state.engine_adapter.get_status()
        return HealthResponse(
            status="ok",
            service="strata_backend",
            engine=EngineHealthModel(
                name=engine_status["name"],
                status=engine_status["status"],
                initialized=engine_status["initialized"],
            ),
        )

    @application.post("/api/sql/profile")
    def execute_profiled_sql(request: Request, body: SQLProfileRequest) -> dict[str, object]:
        try:
            execution = request.app.state.engine_adapter.execute_profiled(body.sql)
            return _serialize_execution(execution)
        except _CLIENT_QUERY_ERRORS as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "SQL_ERROR", "message": str(exc)},
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected profiled SQL execution failure")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "INTERNAL_ERROR", "message": "Internal database error."},
            ) from exc

    return application


def _configured_data_dir() -> Path:
    """Return the configured app-owned demo database path."""
    value = os.environ.get("STRATA_DATA_DIR")
    return Path(value) if value else _DEFAULT_DATA_DIR


def _serialize_execution(execution: ProfiledExecutionResult) -> dict[str, object]:
    """Convert public engine values to JSON-safe API values."""
    if isinstance(execution.result, QueryResult):
        result = execution.result
        return {
            "kind": "query",
            "columns": [
                {"name": column.name, "type": column.data_type.value, "nullable": column.nullable}
                for column in result.schema.columns
            ],
            "rows": [list(row.values) for row in result.rows],
            "row_count": len(result.rows),
            "profile": _serialize_profile(execution),
        }
    assert isinstance(execution.result, CommandResult)
    return {"kind": "command", "affected_rows": execution.result.affected_rows, "profile": None}


def _serialize_profile(execution: ProfiledExecutionResult) -> dict[str, object] | None:
    """Serialize a public engine QueryProfile without plan/operator inspection."""
    profile = execution.profile
    if profile is None:
        return None
    if isinstance(profile.metrics, TableScanMetrics):
        metrics: dict[str, int] = {"tuples_examined": profile.metrics.tuples_examined}
    else:
        assert isinstance(profile.metrics, IndexScanMetrics)
        metrics = {
            "tree_pages_visited": profile.metrics.tree_pages_visited,
            "leaf_entries_examined": profile.metrics.leaf_entries_examined,
            "rids_selected": profile.metrics.rids_selected,
            "rows_fetched": profile.metrics.rows_fetched,
        }
    condition = None
    if profile.condition is not None:
        condition = {
            "column": profile.condition.column_name,
            "operator": profile.condition.operator,
            "literal": profile.condition.literal,
        }
    return {
        "access_path": profile.access_path,
        "table": profile.table_name,
        "index": profile.index_name,
        "condition": condition,
        "metrics": metrics,
    }


app = create_app()
