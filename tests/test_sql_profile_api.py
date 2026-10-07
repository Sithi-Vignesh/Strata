"""DBthon SQL profile API and demo-bootstrap integration coverage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from fastapi.testclient import TestClient
import pytest

from strata_backend.demo_bootstrap import DemoBootstrapError, TASKS_SCHEMA, bootstrap_demo
from strata_backend.engine_adapter import EngineAdapter
from strata_backend.main import create_app
from strata_engine import ProfiledExecutionResult, StrataEngine


def test_profile_endpoint_serializes_index_and_table_scans(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        indexed = client.post(
            "/api/sql/profile",
            json={"sql": "SELECT id, title, status, priority FROM tasks WHERE status = 'BLOCKED'"},
        )
        assert indexed.status_code == 200
        indexed_data = indexed.json()
        assert indexed_data["kind"] == "query"
        assert indexed_data["row_count"] == len(indexed_data["rows"]) > 0
        assert indexed_data["columns"] == [
            {"name": "id", "type": "INTEGER", "nullable": False},
            {"name": "title", "type": "VARCHAR", "nullable": False},
            {"name": "status", "type": "VARCHAR", "nullable": False},
            {"name": "priority", "type": "VARCHAR", "nullable": False},
        ]
        assert indexed_data["profile"]["access_path"] == "IndexScan"
        assert indexed_data["profile"]["index"] == "tasks_status_idx"
        assert indexed_data["profile"]["condition"] == {
            "column": "status", "operator": "=", "literal": "BLOCKED"
        }
        assert set(indexed_data["profile"]["metrics"]) == {
            "tree_pages_visited", "leaf_entries_examined", "rids_selected", "rows_fetched"
        }

        unindexed = client.post(
            "/api/sql/profile",
            json={
                "sql": "SELECT id, title, status, priority FROM tasks WHERE priority = 'URGENT'"
            },
        )
        assert unindexed.status_code == 200
        unindexed_data = unindexed.json()
        assert unindexed_data["row_count"] > 0
        assert unindexed_data["profile"] == {
            "access_path": "TableScan",
            "table": "tasks",
            "index": None,
            "condition": None,
            "metrics": {"tuples_examined": 1000},
        }


def test_profile_api_errors_commands_cors_and_lifecycle(tmp_path) -> None:
    app = create_app(
        data_dir=tmp_path / "demo",
        product_data_dir=tmp_path / "product",
        frontend_origin="http://ui.test",
    )
    adapter = app.state.engine_adapter
    assert adapter.engine.is_open is False
    with TestClient(app) as client:
        assert adapter.engine.is_open is True
        invalid = client.post("/api/sql/profile", json={"sql": "SELECT FROM tasks"})
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "SQL_ERROR"
        assert "message" in invalid.json()["detail"]

        missing = client.post("/api/sql/profile", json={"sql": "SELECT nope FROM tasks"})
        assert missing.status_code == 400
        unknown_table = client.post("/api/sql/profile", json={"sql": "SELECT id FROM unknown_tasks"})
        assert unknown_table.status_code == 400
        assert client.post("/api/sql/profile", json={"sql": "   "}).status_code == 422

        command = client.post(
            "/api/sql/profile",
            json={"sql": "INSERT INTO tasks VALUES (1001, 'Demo', 'TODO', 'LOW', NULL, 'Website')"},
        )
        assert command.status_code == 200
        assert command.json() == {"kind": "command", "affected_rows": 1, "profile": None}

        deleted = client.post(
            "/api/sql/profile",
            json={"sql": "DELETE FROM tasks WHERE id = 1"},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"kind": "command", "affected_rows": 1, "profile": None}

        updated = client.post(
            "/api/sql/profile",
            json={"sql": "UPDATE tasks SET status = 'DONE' WHERE id = 2"},
        )
        assert updated.status_code == 200
        assert updated.json() == {"kind": "command", "affected_rows": 1, "profile": None}

        cors = client.options(
            "/api/sql/profile",
            headers={"Origin": "http://ui.test", "Access-Control-Request-Method": "POST"},
        )
        assert cors.status_code == 200
        assert cors.headers["access-control-allow-origin"] == "http://ui.test"
    assert adapter.engine.is_open is False


def test_demo_bootstrap_is_idempotent(tmp_path) -> None:
    database = tmp_path / "demo"
    with TestClient(create_app(data_dir=database, product_data_dir=tmp_path / "product")) as client:
        assert client.get("/health").status_code == 200
        first = client.post("/api/sql/profile", json={"sql": "SELECT COUNT(*) FROM tasks"}).json()
        assert first["rows"] == [[1000]]

    with TestClient(create_app(data_dir=database, product_data_dir=tmp_path / "product")) as client:
        second = client.post("/api/sql/profile", json={"sql": "SELECT COUNT(*) FROM tasks"}).json()
        assert second["rows"] == [[1000]]
        indexed = client.post(
            "/api/sql/profile",
            json={"sql": "SELECT id FROM tasks WHERE status = 'BLOCKED'"},
        ).json()
        assert indexed["profile"]["index"] == "tasks_status_idx"

    with StrataEngine(database) as engine:
        tasks = engine.get_table("tasks")
        assert tasks.count() == 1000
        assert [index.name for index in tasks.indexes] == ["tasks_status_idx"]


def test_bootstrap_requires_the_named_status_index(tmp_path) -> None:
    database = tmp_path / "demo"
    with StrataEngine(database) as engine:
        tasks = engine.create_table("tasks", TASKS_SCHEMA)
        engine.create_index("legacy_status_idx", "tasks", "status")

        bootstrap_demo(engine)

        assert [index.name for index in tasks.indexes] == ["legacy_status_idx", "tasks_status_idx"]


def test_bootstrap_rejects_wrong_named_status_index(tmp_path) -> None:
    database = tmp_path / "demo"
    with StrataEngine(database) as engine:
        engine.create_table("tasks", TASKS_SCHEMA)
        engine.create_index("tasks_status_idx", "tasks", "priority")

        with pytest.raises(DemoBootstrapError, match="tasks.status"):
            bootstrap_demo(engine)


def test_engine_adapter_serializes_shared_engine_execution() -> None:
    """Concurrent callers must enter one shared engine execution at a time."""
    probe = _ConcurrentProbeEngine()
    adapter = EngineAdapter(probe)
    caller_start = Barrier(6)
    caller_attempted = Event()
    attempt_lock = Lock()
    attempts = 0

    def execute_from_concurrent_caller() -> ProfiledExecutionResult:
        nonlocal attempts
        caller_start.wait(timeout=1)
        with attempt_lock:
            attempts += 1
            if attempts == 5:
                caller_attempted.set()
        return adapter.execute_profiled("SELECT 1")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(execute_from_concurrent_caller) for _ in range(5)]
        caller_start.wait(timeout=1)
        assert probe.first_execution_started.wait(timeout=1)
        assert caller_attempted.wait(timeout=1)
        try:
            assert not probe.second_execution_started.wait(timeout=0.25)
        finally:
            probe.release_execution.set()
        results = [future.result(timeout=1) for future in futures]

    assert len(results) == 5
    assert probe.max_active == 1


def test_ui3_workload_survives_concurrent_board_requests_and_reopen(tmp_path) -> None:
    """Exercise the real bounded UI-3 workload on one shared temporary engine."""
    database = tmp_path / "demo"
    overview_sql = "SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY status ASC"
    tasks_sql = "SELECT id, title, status, priority, assignee, project FROM tasks ORDER BY id ASC LIMIT 40"
    board_sql = [
        "SELECT id, title, status, priority, assignee, project FROM tasks "
        f"WHERE status = '{status}' ORDER BY id ASC LIMIT 5"
        for status in ("TODO", "IN_PROGRESS", "REVIEW", "BLOCKED", "DONE")
    ]

    app = create_app(data_dir=database, product_data_dir=tmp_path / "product")
    with TestClient(app):
        adapter = app.state.engine_adapter
        assert len(adapter.execute_profiled(overview_sql).result.rows) == 5
        assert len(adapter.execute_profiled(tasks_sql).result.rows) == 40
        with ThreadPoolExecutor(max_workers=5) as executor:
            board_results = list(executor.map(adapter.execute_profiled, board_sql))
        assert [len(result.result.rows) for result in board_results] == [5] * 5

    with TestClient(create_app(data_dir=database, product_data_dir=tmp_path / "product")) as reopened_client:
        response = reopened_client.post("/api/sql/profile", json={"sql": tasks_sql})
        assert response.status_code == 200
        assert response.json()["row_count"] == 40


class _ConcurrentProbeEngine:
    """Minimal engine probe for adapter serialization with bounded coordination."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active = 0
        self.max_active = 0
        self._execution_count = 0
        self.first_execution_started = Event()
        self.second_execution_started = Event()
        self.release_execution = Event()

    def execute_profiled(self, sql: str) -> ProfiledExecutionResult:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self._execution_count += 1
            if self._execution_count == 1:
                self.first_execution_started.set()
            elif self._execution_count == 2:
                self.second_execution_started.set()
        if not self.release_execution.wait(timeout=1):
            raise TimeoutError("Concurrent probe was not released.")
        with self._lock:
            self._active -= 1
        return None  # type: ignore[return-value]
