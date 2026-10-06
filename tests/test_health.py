"""Integration and health endpoint tests for strata_backend.

Validates:
- Successful import of FastAPI app
- Creation and operation of local TestClient
- GET /health HTTP 200 response
- Valid JSON payload with service and engine health verification
- Decoupled communication through EngineAdapter
"""

from fastapi.testclient import TestClient
from strata_backend.main import create_app
from strata_backend.engine_adapter import EngineAdapter
from strata_engine import StrataEngine


def test_app_creation_uses_isolated_database(tmp_path) -> None:
    """Verify an app factory result can be attached to TestClient without default data."""
    client = TestClient(create_app(data_dir=tmp_path / "demo"))
    assert client is not None


def test_health_endpoint_success(tmp_path) -> None:
    """Verify GET /health returns HTTP 200 and matches the expected schema."""
    with TestClient(create_app(data_dir=tmp_path / "demo")) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "strata_backend"
        assert "engine" in data

        engine_info = data["engine"]
        assert engine_info["name"] == "StrataEngine"
        assert engine_info["status"] == "open"
        assert engine_info["initialized"] is True
        assert "data_dir" not in engine_info
        assert str(tmp_path) not in response.text


def test_engine_adapter_isolation() -> None:
    """Verify EngineAdapter correctly communicates with custom StrataEngine instances."""
    custom_engine = StrataEngine(data_dir="test_directory")
    adapter = EngineAdapter(engine=custom_engine)
    status = adapter.get_status()

    assert status["name"] == "StrataEngine"
    assert status["status"] == "initialized"
    assert status["initialized"] is True
    assert status["data_dir"] == "test_directory"
