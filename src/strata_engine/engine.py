"""Core Strata database engine interface.

Phase 0: Provides a minimal StrataEngine class representing the engine boundary
and status check. No persistent storage, catalog, parsing, or query execution
is implemented yet.
"""

from pathlib import Path
from typing import Any, Optional, Union


class StrataEngine:
    """Core relational database engine for Strata.

    In Phase 0, this class provides the foundational interface for backend-engine
    communication and lifecycle initialization. Storage engines, page managers,
    and SQL execution are explicitly deferred to later phases.
    """

    def __init__(self, data_dir: Optional[Union[Path, str]] = None) -> None:
        """Initialize the StrataEngine.

        Args:
            data_dir: Optional filesystem path representing the directory reserved
                for database files. In Phase 0, this path is normalized and stored
                in memory; no filesystem modifications or database files are created.
        """
        self._data_dir: Optional[Path] = Path(data_dir) if data_dir is not None else None
        self._initialized: bool = True

    @property
    def data_dir(self) -> Optional[Path]:
        """Return the configured data directory, if specified."""
        return self._data_dir

    @property
    def is_initialized(self) -> bool:
        """Return whether the engine has been initialized."""
        return self._initialized

    def status(self) -> dict[str, Any]:
        """Return deterministic engine status information.

        Returns:
            dict containing engine metadata, initialization status, and configured path.
        """
        return {
            "name": "StrataEngine",
            "status": "initialized",
            "initialized": self._initialized,
            "data_dir": str(self._data_dir) if self._data_dir else None,
        }

    def execute(self, sql: str) -> None:
        """Placeholder for SQL execution interface.

        Args:
            sql: SQL statement string.

        Raises:
            NotImplementedError: SQL execution is not implemented in Phase 0.
        """
        raise NotImplementedError(
            "SQL execution is not implemented in Phase 0. "
            "Storage manager, catalog, and query execution engine will be added in future phases."
        )
