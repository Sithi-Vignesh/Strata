"""Engine Adapter for Strata Backend.

Decouples the FastAPI application routes from the internal details of StrataEngine.
Provides a clean interface that the backend uses to query engine status and, in future
phases, execute queries and manage transactions.
"""

from threading import Lock
from typing import Any, Optional
from strata_engine import ProfiledExecutionResult, StrataEngine


class EngineAdapter:
    """Adapter bridging the FastAPI backend and the Strata database engine."""

    def __init__(self, engine: Optional[StrataEngine] = None) -> None:
        """Initialize the adapter with a StrataEngine instance.

        Args:
            engine: Optional StrataEngine instance. If omitted, a default instance
                is created.
        """
        self._engine: StrataEngine = engine if engine is not None else StrataEngine()
        self._execution_lock = Lock()

    @property
    def engine(self) -> StrataEngine:
        """Return the underlying engine instance."""
        return self._engine

    def get_status(self) -> dict[str, Any]:
        """Retrieve current engine status via the StrataEngine interface.

        Returns:
            dict containing engine metadata and operational state.
        """
        return self._engine.status()

    def execute_profiled(self, sql: str) -> ProfiledExecutionResult:
        """Run one profiled query at a time against the shared engine instance."""
        with self._execution_lock:
            return self._engine.execute_profiled(sql)
