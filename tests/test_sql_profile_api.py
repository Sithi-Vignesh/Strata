"""DBthon SQL profile API and demo-bootstrap integration coverage."""

from fastapi.testclient import TestClient
import pytest

from strata_backend.demo_bootstrap import DemoBootstrapError, TASKS_SCHEMA, bootstrap_demo
from strata_backend.main import create_app
from strata_engine import StrataEngine


def test_profile_endpoint_serializes_index_and_table_scans(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo")
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
    app = create_app(data_dir=tmp_path / "demo", frontend_origin="http://ui.test")
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

        cors = client.options(
            "/api/sql/profile",
            headers={"Origin": "http://ui.test", "Access-Control-Request-Method": "POST"},
        )
        assert cors.status_code == 200
        assert cors.headers["access-control-allow-origin"] == "http://ui.test"
    assert adapter.engine.is_open is False


def test_demo_bootstrap_is_idempotent(tmp_path) -> None:
    database = tmp_path / "demo"
    with TestClient(create_app(data_dir=database)) as client:
        assert client.get("/health").status_code == 200
        first = client.post("/api/sql/profile", json={"sql": "SELECT COUNT(*) FROM tasks"}).json()
        assert first["rows"] == [[1000]]

    with TestClient(create_app(data_dir=database)) as client:
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
