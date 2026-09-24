"""Core Strata database engine interface.

Phase 5: Integrates System Catalog, Schema, and Table storage management
with deterministic engine lifecycle and context management.
"""

from pathlib import Path
from typing import Any, List, Optional, Union

from strata_engine.catalog.catalog import Catalog
from strata_engine.catalog.table import Table
from strata_engine.commands import CreateTableCommand, InsertCommand
from strata_engine.planning import Planner
from strata_engine.planning import QueryRequest
from strata_engine.result import CommandResult, QueryResult
from strata_engine.schema.schema import Schema
from strata_engine.sql import Binder, Lexer, Parser
from strata_engine.storage.exceptions import StorageClosedError


class StrataEngine:
    """Core relational database engine for Strata."""

    def __init__(self, data_dir: Optional[Union[Path, str]] = None) -> None:
        """Initialize the StrataEngine.

        Args:
            data_dir: Optional filesystem path representing the directory reserved
                for database files. If omitted, the engine remains initialized in an
                unopened state until open() is called with a directory or an error is raised.
        """
        self._data_dir: Optional[Path] = Path(data_dir) if data_dir is not None else None
        self._initialized: bool = True
        self._is_open: bool = False
        self._catalog: Optional[Catalog] = None

    @property
    def data_dir(self) -> Optional[Path]:
        """Return the configured data directory, if specified."""
        return self._data_dir

    @property
    def is_initialized(self) -> bool:
        """Return whether the engine has been initialized."""
        return self._initialized

    @property
    def is_open(self) -> bool:
        """Return whether the engine is currently open and ready for database operations."""
        return self._is_open and self._catalog is not None and not self._catalog.is_closed

    @property
    def catalog(self) -> Catalog:
        """Return the active Catalog instance.

        Raises:
            StorageClosedError: If the engine is not currently open.
        """
        if not self.is_open or self._catalog is None:
            raise StorageClosedError("Cannot access Catalog on closed StrataEngine. Call open() first.")
        return self._catalog

    def open(self) -> "StrataEngine":
        """Open the database engine and initialize its System Catalog.

        Returns:
            self: For fluent chaining.

        Raises:
            StorageClosedError: If data_dir was not specified.
        """
        if self._data_dir is None:
            raise StorageClosedError("Cannot open StrataEngine without a configured data_dir.")

        if self.is_open:
            return self

        self._catalog = Catalog(self._data_dir)
        self._is_open = True
        return self

    def close(self) -> None:
        """Close the database engine and release all open table and catalog resources."""
        if not self._is_open and self._catalog is None:
            return

        self._is_open = False
        if self._catalog is not None:
            try:
                self._catalog.close()
            finally:
                self._catalog = None

    def create_table(self, name: str, schema: Schema) -> Table:
        """Create a new table in the database.

        Args:
            name: Table name.
            schema: Table schema.

        Returns:
            Table: Open Table instance.

        Raises:
            StorageClosedError: If the engine is closed.
        """
        return self.catalog.create_table(name, schema)

    def get_table(self, name: str) -> Table:
        """Retrieve an open Table by name.

        Args:
            name: Table name.

        Returns:
            Table: Open Table instance.

        Raises:
            StorageClosedError: If the engine is closed.
            TableNotFoundError: If the table does not exist.
        """
        return self.catalog.get_table(name)

    def has_table(self, name: str) -> bool:
        """Check if a table exists in the database."""
        if not self.is_open:
            return False
        return self.catalog.has_table(name)

    def drop_table(self, name: str) -> None:
        """Drop a table by name.

        Args:
            name: Table name.

        Raises:
            StorageClosedError: If the engine is closed.
            TableNotFoundError: If the table does not exist.
        """
        self.catalog.drop_table(name)

    def list_tables(self) -> List[str]:
        """Return a list of user table names."""
        return self.catalog.list_tables()

    def status(self) -> dict[str, Any]:
        """Return deterministic engine status information.

        Returns:
            dict containing engine metadata, initialization/open status, and configured path.
        """
        current_status = "open" if self.is_open else "initialized"
        return {
            "name": "StrataEngine",
            "status": current_status,
            "initialized": self._initialized,
            "data_dir": str(self._data_dir) if self._data_dir else None,
        }

    def execute(self, sql: str) -> QueryResult | CommandResult:
        """Execute one supported SELECT statement or constrained INSERT command.

        The engine owns the complete operator lifecycle; returned rows remain
        usable after their operator has closed.
        """
        statement = Parser(Lexer(sql).tokenize()).parse()
        bound = Binder(self.catalog).bind(statement)
        if isinstance(bound, QueryRequest):
            plan = Planner().plan(bound)
            operator = plan.create_operator()
            schema = operator.schema
            with operator:
                rows = tuple(operator)
            return QueryResult(schema=schema, rows=rows)
        if isinstance(bound, InsertCommand):
            bound.table.insert(bound.values)
            return CommandResult(affected_rows=1)
        if isinstance(bound, CreateTableCommand):
            self.create_table(bound.table_name, bound.schema)
            return CommandResult(affected_rows=0)
        raise TypeError(f"Unsupported bound statement type {type(bound).__name__}.")

    def __enter__(self) -> "StrataEngine":
        return self.open()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        status_str = "open" if self.is_open else "closed"
        return f"StrataEngine(data_dir='{self._data_dir}', status='{status_str}')"
