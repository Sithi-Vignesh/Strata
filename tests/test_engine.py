"""Unit tests for the strata_engine package.

Validates the Phase 0 foundational requirements:
- Successful import and initialization
- Handling of optional data directory paths without touching disk
- Deterministic status reporting
- Interface placeholder for SQL execution raising NotImplementedError
"""

from pathlib import Path
import pytest
from strata_engine import StrataEngine


def test_engine_import() -> None:
    """Verify StrataEngine can be imported from strata_engine."""
    from strata_engine.engine import StrataEngine as DirectStrataEngine

    assert StrataEngine is DirectStrataEngine


def test_engine_initialization_default() -> None:
    """Verify StrataEngine initializes cleanly with default arguments."""
    engine = StrataEngine()
    assert engine.is_initialized is True
    assert engine.data_dir is None


def test_engine_initialization_with_custom_path() -> None:
    """Verify StrataEngine accepts and normalizes an optional data directory."""
    test_path_str = "custom_data_dir"
    engine_from_str = StrataEngine(data_dir=test_path_str)
    assert engine_from_str.data_dir == Path(test_path_str)

    test_path_obj = Path("another_data_dir")
    engine_from_path = StrataEngine(data_dir=test_path_obj)
    assert engine_from_path.data_dir == test_path_obj


def test_engine_status_structure_and_values() -> None:
    """Verify status method returns deterministic, expected structure and keys."""
    engine = StrataEngine(data_dir="runtime_data")
    status = engine.status()

    assert isinstance(status, dict)
    assert status["name"] == "StrataEngine"
    assert status["status"] == "initialized"
    assert status["initialized"] is True
    assert status["data_dir"] == "runtime_data"


def test_engine_status_determinism() -> None:
    """Verify repeated status calls yield identical results."""
    engine = StrataEngine()
    first_call = engine.status()
    second_call = engine.status()

    assert first_call == second_call
    assert first_call == {
        "name": "StrataEngine",
        "status": "initialized",
        "initialized": True,
        "data_dir": None,
    }


def test_engine_does_not_claim_sql_execution() -> None:
    """Verify execute placeholder raises NotImplementedError and does not claim SQL support."""
    engine = StrataEngine()
    with pytest.raises(NotImplementedError) as exc_info:
        engine.execute("SELECT 1;")

    assert "SQL execution is not implemented in Phase 0" in str(exc_info.value)
