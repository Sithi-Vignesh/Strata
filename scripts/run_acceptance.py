#!/usr/bin/env python3
"""Run STRATA's coordinated release acceptance workflow."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SCHEMA_VERSION = 1
STATUSES = {"passed", "failed", "skipped", "blocked", "not_executed"}
TEMP_PREFIXES = ("strata-e2e-", "strata-benchmark-", "strata-smoke-", "strata-web-smoke-")


@dataclass(frozen=True)
class StageSpec:
    name: str
    title: str
    command: tuple[str, ...] | None = None
    cwd: Path = ROOT
    timeout: float = 300
    required: bool = True
    depends_on: tuple[str, ...] = ("preflight",)
    validator: Callable[["AcceptanceRunner", dict[str, Any]], None] | None = None


@dataclass
class AcceptanceRunner:
    mode: str
    output_dir: Path
    json_console: bool = False
    run_id: str = field(default_factory=lambda: f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}")
    stages: list[dict[str, Any]] = field(default_factory=list)
    interrupted: bool = False

    def __post_init__(self) -> None:
        self.output_dir = self.output_dir.resolve()
        self.logs_dir = self.output_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.initial_temp_artifacts = temporary_artifacts()
        self.started = datetime.now(timezone.utc)

    def emit(self, message: str) -> None:
        if not self.json_console:
            print(message, flush=True)

    def result_for(self, name: str) -> dict[str, Any] | None:
        return next((stage for stage in self.stages if stage["name"] == name), None)

    def append(self, result: dict[str, Any]) -> None:
        if result["status"] not in STATUSES:
            raise ValueError(f"Invalid stage status {result['status']!r}.")
        self.stages.append(result)

    def run_preflight(self) -> None:
        started = time.monotonic()
        missing: list[str] = []
        python = Path(sys.executable)
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        node = shutil.which("node")
        required_paths = (
            ROOT / "pyproject.toml", FRONTEND / "package.json",
            FRONTEND / "node_modules" / "@playwright" / "test",
            ROOT / "benchmarks" / "run.py", ROOT / "scripts" / "smoke_test.py",
        )
        if not python.exists():
            missing.append(f"Python executable: {python}")
        if npm is None:
            missing.append("npm executable")
        if node is None:
            missing.append("Node.js executable")
        missing.extend(str(path) for path in required_paths if not path.exists())
        details = {"python": str(python), "node": node, "npm": npm, "missing": missing}
        self.append(base_result(
            "preflight", "Dependency and repository preflight",
            "passed" if not missing else "failed", time.monotonic() - started,
            required=True, details=details,
            failure_category=None if not missing else "missing_dependency",
            failure_reason=None if not missing else "Missing: " + ", ".join(missing),
        ))

    def run_stage(self, spec: StageSpec) -> None:
        if self.interrupted:
            self.append(base_result(spec.name, spec.title, "not_executed", 0, required=spec.required, failure_category="interrupted", failure_reason="Run was interrupted."))
            return
        unavailable = [name for name in spec.depends_on if (self.result_for(name) or {}).get("status") != "passed"]
        if unavailable:
            self.append(base_result(spec.name, spec.title, "blocked", 0, required=spec.required, failure_category="prerequisite_failed", failure_reason=f"Prerequisite stages did not pass: {', '.join(unavailable)}."))
            return
        if spec.command is None:
            raise ValueError(f"Stage {spec.name} has no command.")
        log_path = self.logs_dir / f"{spec.name}.log"
        self.emit(f"[{spec.name}] starting: {' '.join(spec.command)}")
        result = run_process(spec, log_path)
        result["artifacts"] = [str(log_path)]
        if result["failure_category"] == "interrupted":
            self.interrupted = True
        if result["status"] == "passed" and spec.validator is not None:
            try:
                spec.validator(self, result)
            except Exception as exc:
                result.update(status="failed", failure_category="invalid_report", failure_reason=f"{type(exc).__name__}: {exc}")
        self.append(result)
        self.emit(f"[{spec.name}] {result['status']} in {result['duration_seconds']:.2f}s")

    def run_optional_demo(self) -> None:
        started = time.monotonic()
        marker = ROOT / ".verification" / "demo" / ".strata-demo.json"
        runtime = ROOT / ".verification" / "demo" / "runtime.json"
        if not marker.exists():
            self.append(base_result("demo_readiness", "Persistent demo readiness", "skipped", time.monotonic() - started, required=False, failure_category="demo_unavailable", failure_reason="The owned persistent demo is not initialized."))
            return
        if not runtime.exists():
            self.append(base_result("demo_readiness", "Persistent demo readiness", "skipped", time.monotonic() - started, required=False, failure_category="demo_unavailable", failure_reason="The owned persistent demo is initialized but not running."))
            return
        try:
            marker_data = load_json(marker)
            runtime_data = load_json(runtime)
            expected_root = str((ROOT / ".verification" / "demo").resolve())
            owned = marker_data.get("kind") == "strata-persistent-demo" and marker_data.get("root") == expected_root
            ready = runtime_data.get("kind") == "strata-demo-runtime" and runtime_data.get("root") == expected_root and runtime_data.get("state") == "ready"
        except Exception as exc:
            self.append(base_result("demo_readiness", "Persistent demo readiness", "blocked", time.monotonic() - started, required=False, failure_category="unsafe_storage", failure_reason=str(exc)))
            return
        if not owned:
            self.append(base_result("demo_readiness", "Persistent demo readiness", "blocked", time.monotonic() - started, required=False, failure_category="unsafe_storage", failure_reason="Demo marker identity does not match the default owned root."))
            return
        if not ready:
            self.append(base_result("demo_readiness", "Persistent demo readiness", "skipped", time.monotonic() - started, required=False, failure_category="demo_unavailable", failure_reason="The owned demo is initialized but not running."))
            return
        self.run_stage(StageSpec(
            "demo_readiness", "Persistent demo readiness",
            (sys.executable, "scripts/demo.py", "verify", "--json"), timeout=45,
            required=False, validator=validate_demo_report,
        ))

    def run_cleanup_audit(self) -> None:
        started = time.monotonic()
        remaining = sorted(str(path) for path in temporary_artifacts() - self.initial_temp_artifacts)
        benchmark_stages = [stage for stage in self.stages if stage["name"].startswith("benchmark_") and stage["status"] == "passed"]
        benchmark_cleanup = all(stage.get("details", {}).get("temporary_root_removed") is True for stage in benchmark_stages)
        passed = not remaining and benchmark_cleanup
        self.append(base_result(
            "cleanup_audit", "Disposable-storage cleanup audit", "passed" if passed else "failed",
            time.monotonic() - started, required=True,
            details={"unexpected_temporary_directories": remaining, "benchmark_cleanup_confirmed": benchmark_cleanup},
            failure_category=None if passed else "cleanup_failure",
            failure_reason=None if passed else "Disposable acceptance storage was not fully removed.",
        ))

    def finish(self) -> dict[str, Any]:
        finished = datetime.now(timezone.utc)
        required_failures = [stage for stage in self.stages if stage["required"] and stage["status"] != "passed"]
        verdict = "passed" if not required_failures and not self.interrupted else "failed"
        metadata = environment_metadata()
        report = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "mode": self.mode,
            "status": verdict,
            "started_at": self.started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": round((finished - self.started).total_seconds(), 3),
            "environment": metadata,
            "stages": self.stages,
            "summary": {
                status: sum(stage["status"] == status for stage in self.stages)
                for status in sorted(STATUSES)
            },
            "cleanup_status": (self.result_for("cleanup_audit") or {}).get("status", "not_executed"),
            "overall_verdict": "READY FOR FINAL MANUAL REVIEW" if verdict == "passed" else "NOT READY",
            "artifacts": {
                "directory": str(self.output_dir),
                "json": str(self.output_dir / "acceptance.json"),
                "markdown": str(self.output_dir / "summary.md"),
                "logs": str(self.logs_dir),
            },
        }
        (self.output_dir / "acceptance.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (self.output_dir / "summary.md").write_text(markdown_summary(report), encoding="utf-8")
        return report


def base_result(
    name: str, title: str, status: str, duration: float, *, required: bool,
    details: dict[str, Any] | None = None, failure_category: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name, "title": title, "status": status, "required": required,
        "duration_seconds": round(duration, 3), "command": None, "exit_code": None,
        "test_counts": {}, "artifacts": [], "details": details or {},
        "failure_category": failure_category, "failure_reason": failure_reason,
    }


def run_process(spec: StageSpec, log_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    result = base_result(spec.name, spec.title, "not_executed", 0, required=spec.required)
    result["command"] = list(spec.command or ())
    process: subprocess.Popen[str] | None = None
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            kwargs: dict[str, Any] = {
                "cwd": spec.cwd, "stdout": log, "stderr": subprocess.STDOUT,
                "text": True, "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen(list(spec.command or ()), **kwargs)
            try:
                exit_code = process.wait(timeout=spec.timeout)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                exit_code = process.poll()
                result.update(status="failed", failure_category="timeout", failure_reason=f"Stage exceeded {spec.timeout:.0f}s timeout.")
            except KeyboardInterrupt:
                terminate_process_tree(process)
                exit_code = process.poll()
                result.update(status="failed", failure_category="interrupted", failure_reason="Acceptance run interrupted by the user.")
            result["exit_code"] = exit_code
        output = log_path.read_text(encoding="utf-8", errors="replace")
        result["test_counts"] = parse_test_counts(output)
        if result["status"] == "not_executed":
            if exit_code == 0:
                result["status"] = "passed"
            else:
                category = classify_failure(output)
                result.update(status="failed", failure_category=category, failure_reason=f"Command exited with code {exit_code}. See {log_path}.")
    except FileNotFoundError as exc:
        result.update(status="failed", failure_category="missing_dependency", failure_reason=str(exc))
    except Exception as exc:
        if process is not None and process.poll() is None:
            terminate_process_tree(process)
        result.update(status="failed", failure_category="subprocess_failure", failure_reason=f"{type(exc).__name__}: {exc}")
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        import signal
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def classify_failure(output: str) -> str:
    lowered = output.lower()
    if "executable doesn't exist" in lowered or "cannot find" in lowered or "not recognized" in lowered:
        return "missing_dependency"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "refusing" in lowered and ("storage" in lowered or "directory" in lowered):
        return "unsafe_storage"
    return "subprocess_failure"


def parse_test_counts(output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    patterns = {
        "passed": (r"(\d+) passed", r"Tests\s+(\d+) passed"),
        "failed": (r"(\d+) failed", r"Tests\s+(\d+) failed"),
        "skipped": (r"(\d+) skipped",),
    }
    for label, expressions in patterns.items():
        values = [int(value) for expression in expressions for value in re.findall(expression, output)]
        if values:
            counts[label] = max(values)
    return counts


def validate_benchmark_report(runner: AcceptanceRunner, result: dict[str, Any]) -> None:
    profile = "full" if result["name"] == "benchmark_full" else "smoke"
    path = runner.output_dir / f"benchmark-{profile}" / "results.json"
    report = load_json(path)
    required_workloads = {"full_table_scan", "equality_filter_index", "range_filter_index", "order_by_limit", "aggregation", "group_by", "inner_join"}
    if report.get("schema_version") != 1 or report.get("status") != "passed":
        raise ValueError("Benchmark report schema/status is invalid.")
    if not report.get("datasets"):
        raise ValueError("Benchmark report has no datasets.")
    for dataset in report["datasets"]:
        names = {item.get("name") for item in dataset.get("workloads", [])}
        if not required_workloads <= names:
            raise ValueError(f"Benchmark dataset is missing workloads: {sorted(required_workloads - names)}")
        for workload in dataset["workloads"]:
            latency = workload.get("latency_ms", {})
            if not all(isinstance(latency.get(key), (int, float)) for key in ("minimum", "median", "p95", "maximum")):
                raise ValueError("Benchmark timing fields are missing or invalid.")
    for section in ("integrity", "concurrency", "compensation"):
        if report.get(section, {}).get("status") != "passed":
            raise ValueError(f"Benchmark {section} checks did not pass.")
    if report.get("cleanup", {}).get("temporary_root_removed") is not True:
        raise ValueError("Benchmark temporary storage was not removed.")
    result["details"] = {
        "profile": report["profile"],
        "datasets": [item["size"] for item in report["datasets"]],
        "integrity": report["integrity"]["status"],
        "concurrency": report["concurrency"],
        "compensation": report["compensation"]["status"],
        "temporary_root_removed": True,
    }
    result["artifacts"].extend([str(path), str(path.with_name("report.md"))])


def validate_demo_report(_runner: AcceptanceRunner, result: dict[str, Any]) -> None:
    report = load_json(ROOT / ".verification" / "demo" / "verification.json")
    if report.get("status") != "passed" or any(item.get("status") != "passed" for item in report.get("checks", [])):
        raise ValueError("Persistent demo verification did not pass all checks.")
    result["details"] = {"checks": len(report["checks"])}
    result["artifacts"].append(str(ROOT / ".verification" / "demo" / "verification.json"))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON report {path} must be an object.")
    return value


def temporary_artifacts() -> set[Path]:
    root = Path(tempfile.gettempdir()).resolve()
    try:
        return {path.resolve() for path in root.iterdir() if path.is_dir() and path.name.startswith(TEMP_PREFIXES)}
    except OSError:
        return set()


def environment_metadata() -> dict[str, Any]:
    def output(command: list[str]) -> str:
        try:
            return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unavailable"
    status = output(["git", "status", "--porcelain"])
    return {
        "git_commit": output(["git", "rev-parse", "HEAD"]),
        "git_branch": output(["git", "branch", "--show-current"]),
        "dirty_worktree": bool(status),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "node": output(["node", "--version"]),
        "npm": output(["npm.cmd" if os.name == "nt" else "npm", "--version"]),
        "operating_system": platform.platform(),
    }


def markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# STRATA acceptance summary", "",
        f"- Run: `{report['run_id']}`", f"- Mode: `{report['mode']}`",
        f"- Status: **{report['status']}**", f"- Verdict: **{report['overall_verdict']}**",
        f"- Git: `{report['environment']['git_commit']}` (dirty: `{report['environment']['dirty_worktree']}`)", "",
        "| Stage | Required | Status | Duration (s) | Tests | Failure |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for stage in report["stages"]:
        counts = ", ".join(f"{key}={value}" for key, value in stage["test_counts"].items()) or "—"
        failure = stage["failure_reason"] or "—"
        lines.append(f"| {stage['title']} | {stage['required']} | **{stage['status']}** | {stage['duration_seconds']:.3f} | {counts} | {failure} |")
    lines.extend(["", f"Logs and machine-readable evidence: `{report['artifacts']['directory']}`", ""])
    return "\n".join(lines)


def stage_specs(mode: str, output: Path) -> list[StageSpec]:
    python = sys.executable
    npm = "npm.cmd" if os.name == "nt" else "npm"
    smoke_backend = (
        "tests/test_scope_c_backend.py", "tests/test_adversarial_api.py",
        "tests/test_concurrency.py", "tests/test_adversarial_concurrency.py",
        "tests/test_adversarial_service.py", "tests/test_adversarial_storage.py",
        "tests/test_demo_environment.py", "tests/test_benchmark_harness.py",
    )
    browser_args = (npm, "run", "e2e") if mode == "full" else (npm, "run", "e2e", "--", "--grep", "@release")
    backend_args = (python, "-m", "pytest", "-q") if mode == "full" else (python, "-m", "pytest", "-q", *smoke_backend)
    specs = [
        StageSpec("runner_self_tests", "Acceptance runner self-tests", (python, "-m", "pytest", "-q", "tests/test_acceptance_runner.py"), timeout=120),
        StageSpec("backend_regression", "Backend, integrity, and concurrency regression", backend_args, timeout=900),
        StageSpec("frontend_tests", "Frontend unit and component tests", (npm, "test"), cwd=FRONTEND, timeout=360),
        StageSpec("typescript", "TypeScript checks", (npm, "run", "typecheck"), cwd=FRONTEND, timeout=240),
        StageSpec("frontend_build", "Frontend production build", (npm, "run", "build"), cwd=FRONTEND, timeout=300, depends_on=("preflight", "typescript")),
        StageSpec("playwright_typecheck", "Playwright TypeScript checks", (npm, "run", "e2e:typecheck"), cwd=FRONTEND, timeout=180),
        StageSpec("browser_acceptance", "Real Chromium browser acceptance", browser_args, cwd=FRONTEND, timeout=1200, depends_on=("preflight", "frontend_build", "playwright_typecheck")),
        StageSpec("http_restart", "Real HTTP collaboration and restart smoke", (python, "scripts/smoke_test.py", "--frontend"), timeout=360),
        StageSpec("benchmark_smoke", "P2 benchmark and integrity smoke", (python, "benchmarks/run.py", "--profile", "smoke", "--output-dir", str(output / "benchmark-smoke")), timeout=900, validator=validate_benchmark_report),
    ]
    if mode == "full":
        specs.append(StageSpec("benchmark_full", "P2 full benchmark profile", (python, "benchmarks/run.py", "--profile", "full", "--output-dir", str(output / "benchmark-full")), timeout=1800, validator=validate_benchmark_report))
    specs.append(StageSpec("diff_check", "Git whitespace error check", ("git", "diff", "--check"), timeout=120))
    return specs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--smoke", action="store_true", help="Run the bounded release smoke profile (default).")
    modes.add_argument("--full", action="store_true", help="Run all backend/browser tests and the full P2 benchmark profile.")
    parser.add_argument("--json", action="store_true", help="Print only the final machine-readable report to stdout.")
    parser.add_argument("--output", type=Path, help="Report directory; defaults to a unique ignored .verification/acceptance run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "full" if args.full else "smoke"
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output = args.output or ROOT / ".verification" / "acceptance" / run_id
    runner = AcceptanceRunner(mode, output, args.json, run_id)
    runner.run_preflight()
    for spec in stage_specs(mode, runner.output_dir):
        runner.run_stage(spec)
    runner.run_optional_demo()
    runner.run_cleanup_audit()
    report = runner.finish()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        runner.emit(f"Report: {report['artifacts']['json']}")
        runner.emit(f"Verdict: {report['overall_verdict']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
