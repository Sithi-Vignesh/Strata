"""FastAPI application for Strata.

Phase 0: Provides the application entrypoint and the GET /health endpoint,
verifying communication between the backend and StrataEngine via EngineAdapter.
"""

from typing import Optional
from fastapi import FastAPI, status
from pydantic import BaseModel, Field

from strata_backend.engine_adapter import EngineAdapter


class EngineStatusModel(BaseModel):
    """Pydantic model representing StrataEngine status."""

    name: str = Field(..., description="Name of the database engine")
    status: str = Field(..., description="Operational status of the engine")
    initialized: bool = Field(..., description="Whether the engine is initialized")
    data_dir: Optional[str] = Field(None, description="Configured data directory path")


class HealthResponse(BaseModel):
    """Pydantic model representing the /health response payload."""

    status: str = Field(..., description="Status of the backend service")
    service: str = Field(..., description="Name of the backend service")
    engine: EngineStatusModel = Field(..., description="Status of the underlying database engine")


app = FastAPI(
    title="Strata API",
    description="Collaborative project and task management backend powered by StrataEngine",
    version="0.1.0",
)

# Shared adapter instance bridging backend and engine
engine_adapter = EngineAdapter()


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="System Health & Connectivity Check",
    tags=["System"],
)
def get_health() -> HealthResponse:
    """Check health of the backend and confirm connectivity to StrataEngine.

    In Phase 0, this validates that the FastAPI backend successfully communicates
    with the StrataEngine through the EngineAdapter. No database queries are executed.
    """
    engine_status = engine_adapter.get_status()
    return HealthResponse(
        status="ok",
        service="strata_backend",
        engine=EngineStatusModel(**engine_status),
    )
