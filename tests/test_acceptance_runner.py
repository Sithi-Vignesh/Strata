"""Failure-reporting and isolation tests for the P4 acceptance orchestrator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("strata_acceptance_runner", ROOT / "scripts" / "run_acceptance.py")
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def run_spec(tmp_path: Path, name: str, command: tuple[str, ...], timeout: float = 10):
    spec = acceptance.StageSpec(name, name, command, cwd=ROOT, timeout=timeout)
    return acceptance.run_process(spec, tmp_path / f"{name}.log")


def test_subprocess_success_and_failure_are_not_conflated(tmp_path: Path) -> None:
    passed = run_spec(tmp_path, "passed", (sys.executable, "-c", "print('3 passed')"))
    failed = run_spec(tmp_path, "failed", (sys.executable, "-c", "import sys; print('assertion failed'); sys.exit(7)"))

    assert passed["status"] == "passed" and passed["exit_code"] == 0
    assert passed["test_counts"] == {"passed": 3}
    assert failed["status"] == "failed" and failed["exit_code"] == 7
    assert failed["failure_category"] == "subprocess_failure"


def test_timeout_and_missing_dependency_are_explicit(tmp_path: Path) -> None:
    timed_out = run_spec(tmp_path, "timeout", (sys.executable, "-c", "import time; time.sleep(5)"), timeout=0.1)
    missing = run_spec(tmp_path, "missing", (str(tmp_path / "definitely-missing-command.exe"),))

    assert timed_out["status"] == "failed"
    assert timed_out["failure_category"] == "timeout"
    assert missing["status"] == "failed"
    assert missing["failure_category"] == "missing_dependency"


def test_invalid_benchmark_json_cannot_pass_validation(tmp_path: Path) -> None:
    output = tmp_path / "acceptance"
    path = output / "benchmark-smoke" / "results.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")
    runner = acceptance.AcceptanceRunner("smoke", output)
    result = {"name": "benchmark_smoke", "artifacts": [], "details": {}}

    with pytest.raises(ValueError, match="Invalid JSON"):
        acceptance.validate_benchmark_report(runner, result)


def test_interruption_browser_and_storage_failures_are_classified() -> None:
    interrupted = acceptance.base_result(
        "stage", "Stage", "failed", 0, required=True,
        failure_category="interrupted", failure_reason="Acceptance run interrupted by the user.",
    )
    assert interrupted["status"] == "failed"
    assert interrupted["failure_category"] == "interrupted"
    assert acceptance.classify_failure("browser executable doesn't exist") == "missing_dependency"
    assert acceptance.classify_failure("Refusing destructive work outside verified storage directory") == "unsafe_storage"


def test_cleanup_failure_changes_required_stage_to_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acceptance.tempfile, "gettempdir", lambda: str(tmp_path))
    runner = acceptance.AcceptanceRunner("smoke", tmp_path / "reports")
    leaked = tmp_path / "strata-e2e-controlled-leak"
    leaked.mkdir()
    runner.run_cleanup_audit()

    result = runner.result_for("cleanup_audit")
    assert result is not None
    assert result["status"] == "failed"
    assert result["failure_category"] == "cleanup_failure"


def test_optional_demo_unavailable_is_skipped_not_passed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = acceptance.AcceptanceRunner("smoke", tmp_path / "reports")
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    runner.run_optional_demo()

    result = runner.result_for("demo_readiness")
    assert result is not None
    assert result["status"] == "skipped"
    assert result["failure_category"] == "demo_unavailable"


def test_required_blocked_stage_prevents_passing_verdict(tmp_path: Path) -> None:
    runner = acceptance.AcceptanceRunner("smoke", tmp_path / "reports")
    runner.append(acceptance.base_result("preflight", "Preflight", "failed", 0, required=True, failure_category="missing_dependency", failure_reason="missing"))
    runner.run_stage(acceptance.StageSpec("dependent", "Dependent", (sys.executable, "-c", "raise SystemExit(0)")))
    runner.append(acceptance.base_result("cleanup_audit", "Cleanup", "passed", 0, required=True))
    report = runner.finish()

    assert runner.result_for("dependent")["status"] == "blocked"
    assert report["status"] == "failed"
    assert report["overall_verdict"] == "NOT READY"
    persisted = json.loads((tmp_path / "reports" / "acceptance.json").read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
