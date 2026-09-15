"""Integration and health endpoint tests for strata_backend.

Validates:
- Successful import of FastAPI app
- Creation and operation of local TestClient
- GET /health HTTP 200 response
- Valid JSON payload with service and engine health verification
- Decoupled communication through EngineAdapter
"""

from fastapi.testclient import TestClient
from strata_backend.main import app
from strata_backend.engine_adapter import EngineAdapter
from strata_engine import StrataEngine


def test_app_import_and_client_creation() -> None:
    """Verify FastAPI application imports and can be attached to TestClient."""
    client = TestClient(app)
    assert client is not None


def test_health_endpoint_success() -> None:
    """Verify GET /health returns HTTP 200 and matches the expected schema."""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "strata_backend"
    assert "engine" in data

    engine_info = data["engine"]
    assert engine_info["name"] == "StrataEngine"
    assert engine_info["status"] == "initialized"
    assert engine_info["initialized"] is True
    assert engine_info["data_dir"] is None


def test_engine_adapter_isolation() -> None:
    """Verify EngineAdapter correctly communicates with custom StrataEngine instances."""
    custom_engine = StrataEngine(data_dir="test_directory")
    adapter = EngineAdapter(engine=custom_engine)
    status = adapter.get_status()

    assert status["name"] == "StrataEngine"
    assert status["status"] == "initialized"
    assert status["initialized"] is True
    assert status["data_dir"] == "test_directory"
