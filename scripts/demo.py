#!/usr/bin/env python3
"""Manage STRATA's persistent, isolated demonstration environment.

The public commands are intentionally small and PowerShell-friendly::

    python scripts/demo.py init
    python scripts/demo.py start
    python scripts/demo.py verify --json
    python scripts/demo.py stop
    python scripts/demo.py reset --yes
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from strata_backend.demo_bootstrap import bootstrap_demo  # noqa: E402
from strata_backend.product_bootstrap import initialize_product  # noqa: E402
from strata_backend.product_service import ProductConflictError, ProductService  # noqa: E402
from strata_engine import Column, DataType, QueryResult, Schema, StrataEngine  # noqa: E402


DEMO_FORMAT = 1
OWNER = {"name": "Demo Owner", "email": "owner@demo.strata.local", "password": "Strata-Demo-Owner-2026!"}
COLLABORATOR = {
    "name": "Demo Collaborator",
    "email": "collaborator@demo.strata.local",
    "password": "Strata-Demo-Collaborator-2026!",
}
WORKSPACE_NAME = "Atlas Product Team"
DEFAULT_BACKEND_PORT = 18080
DEFAULT_FRONTEND_PORT = 15174


class DemoError(RuntimeError):
    """An actionable demo-environment failure."""


@dataclass(frozen=True)
class DemoPaths:
    root: Path
    product: Path
    sql: Path
    logs: Path
    marker: Path
    runtime: Path
    stop_request: Path
    verification: Path


def demo_paths(root: Path | None = None) -> DemoPaths:
    resolved = (root or REPO_ROOT / ".verification" / "demo").resolve()
    verification_root = (REPO_ROOT / ".verification").resolve()
    try:
        resolved.relative_to(verification_root)
    except ValueError as exc:
        raise DemoError(f"Demo root must be inside {verification_root}; got {resolved}.") from exc
    if resolved.name != "demo" and not resolved.name.startswith("demo-"):
        raise DemoError("Demo root name must be 'demo' or start with 'demo-'.")
    product = resolved / "data" / "product"
    sql = resolved / "data" / "sql"
    developer_paths = {
        (REPO_ROOT / "data" / "strata").resolve(),
        (REPO_ROOT / "data" / "dbthon_demo").resolve(),
    }
    if product.resolve() in developer_paths or sql.resolve() in developer_paths or product == sql:
        raise DemoError("Demo storage overlaps a developer database.")
    return DemoPaths(
        resolved, product, sql, resolved / "logs", resolved / ".strata-demo.json",
        resolved / "runtime.json", resolved / "stop-request.json", resolved / "verification.json",
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoError(f"Invalid demo metadata at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DemoError(f"Demo metadata at {path} must be a JSON object.")
    return value


def _marker_value(paths: DemoPaths) -> dict[str, Any]:
    return {
        "format": DEMO_FORMAT,
        "kind": "strata-persistent-demo",
        "root": str(paths.root),
        "product_store": str(paths.product),
        "sql_store": str(paths.sql),
    }


def validate_marker(paths: DemoPaths) -> None:
    actual = _read_json(paths.marker)
    expected = _marker_value(paths)
    if actual != expected:
        raise DemoError(
            f"Refusing to use {paths.root}: its isolation marker does not exactly match this demo root."
        )


def _open_engine(path: Path) -> StrataEngine:
    engine = StrataEngine(path)
    engine.open()
    return engine


def _demo_user(service: ProductService, account: dict[str, str]):
    authenticated = service.authenticate_user(account["email"], account["password"])
    if authenticated is not None:
        user = service.get_user(authenticated.session.user_id)
        service.revoke_session(authenticated.session.id)
        if user.name != account["name"]:
            raise DemoError(f"Existing demo user {account['email']} has an unexpected name.")
        return user
    try:
        registered = service.register_account(account["name"], account["email"], account["password"])
    except ProductConflictError as exc:
        raise DemoError(
            f"Existing account {account['email']} does not accept the documented demo credentials."
        ) from exc
    service.revoke_session(registered.session.id)
    return registered.user


PROJECTS = {
    "Website Redesign": "Refresh the public experience and content system.",
    "Mobile App Launch": "Coordinate release readiness across product and engineering.",
    "Platform Reliability": "Keep production operations measurable and resilient.",
}


def _task_specs(owner_id: int, collaborator_id: int) -> list[dict[str, Any]]:
    today = date.today()
    return [
        {"project": "Website Redesign", "title": "Publish responsive landing page", "description": "Complete responsive QA and publish the approved launch page.", "status": "IN_PROGRESS", "priority": "HIGH", "assignee": collaborator_id, "due": today, "handoff": "Please own the final responsive QA and post the launch confirmation."},
        {"project": "Website Redesign", "title": "Audit legacy content", "description": "Identify stale pages and record redirect recommendations.", "status": "TODO", "priority": "MEDIUM", "assignee": owner_id, "due": today - timedelta(days=3)},
        {"project": "Website Redesign", "title": "Archive superseded mockups", "description": "Move replaced concepts into the design archive.", "status": "DONE", "priority": "LOW", "assignee": owner_id, "due": today - timedelta(days=1)},
        {"project": "Mobile App Launch", "title": "Prepare app store release notes", "description": "Turn the approved launch narrative into store-ready copy.", "status": "TODO", "priority": "HIGH", "assignee": collaborator_id, "due": today + timedelta(days=7)},
        {"project": "Mobile App Launch", "title": "Validate offline onboarding", "description": "Confirm first-run guidance degrades cleanly without a network.", "status": "IN_PROGRESS", "priority": "MEDIUM", "assignee": None, "due": today + timedelta(days=3)},
        {"project": "Platform Reliability", "title": "Review database backup runbook", "description": "Walk the restore checklist and record any ambiguous steps.", "status": "TODO", "priority": "HIGH", "assignee": owner_id, "due": today - timedelta(days=2)},
        {"project": "Platform Reliability", "title": "Tune notification delivery metrics", "description": "Finalize the alert thresholds used during the launch window.", "status": "DONE", "priority": "MEDIUM", "assignee": collaborator_id, "due": today},
    ]


NOTES = {
    "Publish responsive landing page": ("The accessibility pass is complete; mobile spacing still needs a final check.", "I will validate the 390px and 768px breakpoints before handoff."),
    "Prepare app store release notes": ("Legal approved the privacy wording for both stores.",),
    "Review database backup runbook": ("Use the staging snapshot for the walkthrough; do not touch production data.",),
}


def _seed_product(paths: DemoPaths) -> dict[str, Any]:
    engine = _open_engine(paths.product)
    try:
        initialize_product(engine)
        service = ProductService(engine)
        owner = _demo_user(service, OWNER)
        collaborator = _demo_user(service, COLLABORATOR)

        matches = [item for item in service.list_workspaces_for_user(owner.id, actor_user_id=owner.id) if item.name == WORKSPACE_NAME]
        if len(matches) > 1:
            raise DemoError(f"Multiple workspaces are named {WORKSPACE_NAME!r}; refusing ambiguous initialization.")
        workspace = matches[0] if matches else service.create_workspace(WORKSPACE_NAME, owner.id)
        members = service.list_workspace_members(workspace.id, actor_user_id=owner.id)
        if collaborator.id not in {item.user_id for item in members}:
            service.add_workspace_member_by_email(workspace.id, collaborator.email, actor_user_id=owner.id)

        existing_projects = {item.name: item for item in service.list_projects(workspace.id, actor_user_id=owner.id)}
        projects = {}
        for name, description in PROJECTS.items():
            projects[name] = existing_projects.get(name) or service.create_project(
                workspace.id, name, description, actor_user_id=owner.id,
            )

        tasks_by_title = {
            task.title: task
            for project in projects.values()
            for task in service.list_tasks(project.id, actor_user_id=owner.id)
        }
        for spec in _task_specs(owner.id, collaborator.id):
            project = projects[spec["project"]]
            task = tasks_by_title.get(spec["title"])
            if task is None:
                # The featured task starts with the owner so the real handoff path creates
                # both an assignment notification and a handoff activity record.
                initial_assignee = owner.id if "handoff" in spec else spec["assignee"]
                initial_status = "TODO" if spec["status"] != "TODO" else spec["status"]
                task = service.create_task(
                    project.id, spec["title"], description=spec["description"],
                    status=initial_status, priority=spec["priority"],
                    assignee_user_id=initial_assignee, due_date=spec["due"].isoformat(),
                    actor_user_id=owner.id,
                )
                updates: dict[str, Any] = {}
                if task.status != spec["status"]:
                    updates["status"] = spec["status"]
                if task.assignee_user_id != spec["assignee"]:
                    updates["assignee_user_id"] = spec["assignee"]
                    updates["handoff_note"] = spec["handoff"]
                if updates:
                    task = service.update_task(task.id, actor_user_id=owner.id, **updates)
                tasks_by_title[task.title] = task
            else:
                if task.project_id != project.id:
                    raise DemoError(f"Demo task title {task.title!r} exists in the wrong project.")
                changes = {}
                for field, wanted in (
                    ("description", spec["description"]), ("status", spec["status"]),
                    ("priority", spec["priority"]), ("assignee_user_id", spec["assignee"]),
                    ("due_date", spec["due"].isoformat()),
                ):
                    if getattr(task, field) != wanted:
                        changes[field] = wanted
                if changes:
                    task = service.update_task(task.id, actor_user_id=owner.id, **changes)
                    tasks_by_title[task.title] = task

        for title, contents in NOTES.items():
            task = tasks_by_title[title]
            existing = {note.content for note in service.list_notes(task.id, actor_user_id=owner.id)}
            for index, content in enumerate(contents):
                if content not in existing:
                    author = owner.id if index == 0 else collaborator.id
                    service.create_note(task.id, author, content, actor_user_id=author)

        featured = tasks_by_title["Publish responsive landing page"]
        activity, _ = service.list_task_activity(featured.id, actor_user_id=owner.id)
        notifications, _ = service.list_notifications(actor_user_id=collaborator.id)
        return {
            "owner_id": owner.id,
            "collaborator_id": collaborator.id,
            "workspace_id": workspace.id,
            "project_ids": {name: project.id for name, project in projects.items()},
            "task_count": len(tasks_by_title),
            "featured_task_id": featured.id,
            "activity_count": len(activity),
            "collaborator_notification_count": len(notifications),
        }
    finally:
        engine.close()


def _seed_sql(paths: DemoPaths) -> dict[str, Any]:
    engine = _open_engine(paths.sql)
    try:
        bootstrap_demo(engine)
        if not engine.has_table("demo_projects"):
            engine.execute("CREATE TABLE demo_projects (id INTEGER, name VARCHAR(64), lead VARCHAR(64));")
            for statement in (
                "INSERT INTO demo_projects VALUES (1, 'Website Redesign', 'Avery');",
                "INSERT INTO demo_projects VALUES (2, 'Mobile App Launch', 'Blake');",
                "INSERT INTO demo_projects VALUES (3, 'Platform Reliability', 'Casey');",
            ):
                engine.execute(statement)
        if not engine.has_table("demo_work_items"):
            engine.execute("CREATE TABLE demo_work_items (id INTEGER, project_id INTEGER, title VARCHAR(96), status VARCHAR(16), effort INTEGER);")
            rows = (
                (1, 1, "Responsive QA", "IN_PROGRESS", 5),
                (2, 1, "Content audit", "TODO", 3),
                (3, 2, "Release notes", "TODO", 2),
                (4, 2, "Offline onboarding", "IN_PROGRESS", 8),
                (5, 3, "Backup runbook", "TODO", 5),
                (6, 3, "Delivery metrics", "DONE", 3),
            )
            for row in rows:
                title = row[2].replace("'", "''")
                engine.execute(f"INSERT INTO demo_work_items VALUES ({row[0]}, {row[1]}, '{title}', '{row[3]}', {row[4]});")
        work_items = engine.get_table("demo_work_items")
        status_ordinal = work_items.schema.column_index("status")
        index = next((item for item in work_items.indexes if item.name.lower() == "demo_work_items_status_idx"), None)
        if index is None:
            engine.create_index("demo_work_items_status_idx", "demo_work_items", "status")
        elif index.column_ordinal != status_ordinal:
            raise DemoError("The demo_work_items status index has an incompatible binding.")
        result = engine.execute("SELECT COUNT(*) FROM demo_work_items")
        assert isinstance(result, QueryResult)
        return {"tables": engine.list_tables(), "work_item_count": result.rows[0].values[0]}
    finally:
        engine.close()


def initialize(paths: DemoPaths) -> dict[str, Any]:
    if paths.marker.exists():
        validate_marker(paths)
    elif paths.root.exists() and any(paths.root.iterdir()):
        raise DemoError(f"Refusing to initialize non-empty unmarked directory {paths.root}.")
    else:
        paths.root.mkdir(parents=True, exist_ok=True)
        _atomic_json(paths.marker, _marker_value(paths))
    paths.logs.mkdir(parents=True, exist_ok=True)
    product = _seed_product(paths)
    sql = _seed_sql(paths)
    result = {"status": "passed", "root": str(paths.root), "product": product, "sql": sql}
    _atomic_json(paths.root / "seed.json", result)
    return result


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a portable liveness probe on Windows. Query a
        # limited handle without signaling or otherwise changing the process.
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_url(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1.5) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise DemoError(f"Timed out waiting for {url}: {last_error}")


def _runtime_is_owned(paths: DemoPaths, runtime: dict[str, Any]) -> bool:
    return (
        runtime.get("kind") == "strata-demo-runtime"
        and runtime.get("root") == str(paths.root)
        and isinstance(runtime.get("token"), str)
    )


def start(paths: DemoPaths, backend_port: int, frontend_port: int, timeout: float = 45.0) -> dict[str, Any]:
    if paths.marker.exists():
        validate_marker(paths)
    if paths.runtime.exists():
        runtime = _read_json(paths.runtime)
        if _runtime_is_owned(paths, runtime) and _pid_alive(runtime.get("supervisor_pid")):
            if runtime.get("state") == "ready":
                _wait_url(f"http://127.0.0.1:{runtime['backend_port']}/health", 3)
                return {"status": "passed", "message": "Demo is already running.", **runtime}
            raise DemoError("A demo supervisor is already starting; retry shortly.")
        if any(_pid_alive(runtime.get(key)) for key in ("backend_pid", "frontend_pid")):
            raise DemoError(
                "Stale runtime metadata references live child processes. Refusing PID-based cleanup; "
                "inspect the recorded commands before retrying."
            )
        paths.runtime.unlink(missing_ok=True)
    initialize(paths)
    validate_marker(paths)
    for label, port in (("backend", backend_port), ("frontend", frontend_port)):
        if not 1 <= port <= 65535:
            raise DemoError(f"Invalid {label} port: {port}.")
        if not _port_available(port):
            raise DemoError(f"Port {port} for the {label} is already in use; no process was terminated.")

    python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    vite = REPO_ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    node = shutil.which("node")
    if not python.exists():
        raise DemoError(f"Missing backend environment: {python}. Create/install the project venv first.")
    if node is None or not vite.exists():
        raise DemoError("Missing frontend dependencies. Run npm install in frontend before starting the demo.")

    token = secrets.token_urlsafe(24)
    _atomic_json(paths.runtime, {
        "kind": "strata-demo-runtime", "root": str(paths.root), "token": token,
        "state": "launching", "supervisor_pid": None,
        "backend_port": backend_port, "frontend_port": frontend_port,
    })
    command = [
        str(python), str(Path(__file__).resolve()), "_serve", "--root", str(paths.root),
        "--backend-port", str(backend_port), "--frontend-port", str(frontend_port), "--token", token,
    ]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    supervisor_log = (paths.logs / "supervisor.log").open("a", encoding="utf-8")
    try:
        supervisor = subprocess.Popen(
            command, cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=supervisor_log,
            stderr=subprocess.STDOUT, creationflags=flags,
        )
    finally:
        supervisor_log.close()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if paths.runtime.exists():
            runtime = _read_json(paths.runtime)
            if runtime.get("token") != token:
                raise DemoError("Demo runtime token changed during startup.")
            if runtime.get("state") == "ready":
                return {"status": "passed", "message": "Demo started.", **runtime}
            if runtime.get("state") == "error":
                raise DemoError(str(runtime.get("error", "Demo supervisor failed.")))
        # A Microsoft Store-backed venv may return the PID of a short-lived
        # launcher. The authenticated runtime record contains the real PID.
        if os.name != "nt" and supervisor.poll() is not None:
            raise DemoError(f"Demo supervisor exited during startup (code {supervisor.returncode}).")
        time.sleep(0.25)
    _atomic_json(paths.stop_request, {"token": token})
    raise DemoError(f"Demo startup exceeded {timeout:.0f} seconds; cleanup was requested.")


def _terminate_owned(process: subprocess.Popen[Any], timeout: float = 8.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def supervise(paths: DemoPaths, backend_port: int, frontend_port: int, token: str) -> int:
    validate_marker(paths)
    # The detached child can be scheduled before its parent atomically publishes
    # the PID-bearing launch record. Wait for that one bounded hand-off only.
    runtime: dict[str, Any] | None = None
    launch_deadline = time.monotonic() + 5
    while time.monotonic() < launch_deadline:
        if paths.runtime.exists():
            candidate = _read_json(paths.runtime)
            if candidate.get("token") == token and candidate.get("state") == "launching":
                runtime = candidate
                break
        time.sleep(0.05)
    if runtime is None:
        raise DemoError("Supervisor launch metadata is missing or does not match this process.")
    python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    node = shutil.which("node")
    vite = REPO_ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None:
        raise DemoError("Node.js is not available.")
    environment = os.environ.copy()
    environment.update({
        "STRATA_DATA_DIR": str(paths.sql),
        "STRATA_PRODUCT_DATA_DIR": str(paths.product),
        "STRATA_FRONTEND_ORIGIN": f"http://127.0.0.1:{frontend_port}",
        "STRATA_SESSION_COOKIE_SECURE": "false",
    })
    frontend_environment = environment | {"STRATA_BACKEND_URL": f"http://127.0.0.1:{backend_port}"}
    backend_log = (paths.logs / "backend.log").open("a", encoding="utf-8")
    frontend_log = (paths.logs / "frontend.log").open("a", encoding="utf-8")
    backend = frontend = None
    try:
        backend = subprocess.Popen(
            [str(python), "-m", "uvicorn", "strata_backend.main:app", "--host", "127.0.0.1",
             "--port", str(backend_port), "--workers", "1", "--log-level", "warning", "--no-access-log"],
            cwd=REPO_ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=backend_log, stderr=subprocess.STDOUT,
        )
        frontend = subprocess.Popen(
            [node, str(vite), "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
            cwd=REPO_ROOT / "frontend", env=frontend_environment, stdin=subprocess.DEVNULL,
            stdout=frontend_log, stderr=subprocess.STDOUT,
        )
        _atomic_json(paths.runtime, {
            "kind": "strata-demo-runtime", "root": str(paths.root), "token": token,
            "state": "starting", "supervisor_pid": os.getpid(), "backend_pid": backend.pid,
            "frontend_pid": frontend.pid, "backend_port": backend_port, "frontend_port": frontend_port,
            "started_at": int(time.time()),
        })
        _wait_url(f"http://127.0.0.1:{backend_port}/health", 35)
        _wait_url(f"http://127.0.0.1:{frontend_port}/health", 15)
        runtime = _read_json(paths.runtime)
        runtime["state"] = "ready"
        _atomic_json(paths.runtime, runtime)
        while True:
            if backend.poll() is not None or frontend.poll() is not None:
                raise DemoError(
                    f"A demo service exited unexpectedly (backend={backend.poll()}, frontend={frontend.poll()})."
                )
            if paths.stop_request.exists():
                request = _read_json(paths.stop_request)
                if request.get("token") != token:
                    paths.stop_request.unlink(missing_ok=True)
                    continue
                break
            time.sleep(0.5)
        return 0
    except Exception as exc:
        if paths.runtime.exists():
            current = _read_json(paths.runtime)
            if current.get("token") == token:
                current.update({"state": "error", "error": str(exc)})
                _atomic_json(paths.runtime, current)
        return 1
    finally:
        if frontend is not None:
            _terminate_owned(frontend)
        if backend is not None:
            _terminate_owned(backend)
        frontend_log.close()
        backend_log.close()
        paths.stop_request.unlink(missing_ok=True)
        if paths.runtime.exists():
            try:
                current = _read_json(paths.runtime)
                if current.get("token") == token and current.get("state") != "error":
                    paths.runtime.unlink()
            except DemoError:
                pass


def stop(paths: DemoPaths, timeout: float = 20.0) -> dict[str, Any]:
    validate_marker(paths)
    if not paths.runtime.exists():
        return {"status": "passed", "message": "Demo is already stopped."}
    runtime = _read_json(paths.runtime)
    if not _runtime_is_owned(paths, runtime):
        raise DemoError("Runtime metadata is not owned by this demo root; no process was terminated.")
    if not _pid_alive(runtime.get("supervisor_pid")):
        if any(_pid_alive(runtime.get(key)) for key in ("backend_pid", "frontend_pid")):
            raise DemoError("The supervisor is gone but recorded children are live; refusing unsafe PID cleanup.")
        paths.runtime.unlink(missing_ok=True)
        paths.stop_request.unlink(missing_ok=True)
        return {"status": "passed", "message": "Removed stale stopped-demo metadata."}
    _atomic_json(paths.stop_request, {"token": runtime["token"]})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not paths.runtime.exists() and not _pid_alive(runtime.get("supervisor_pid")):
            return {"status": "passed", "message": "Demo stopped cleanly."}
        time.sleep(0.25)
    raise DemoError("Timed out waiting for the owned demo supervisor to stop its services.")


class JsonClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=5) as response:
                payload = response.read()
                return None if not payload else json.loads(payload)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DemoError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError) as exc:
            raise DemoError(f"{method} {path} failed: {exc}") from exc


def verify(paths: DemoPaths) -> dict[str, Any]:
    started = time.monotonic()
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"name": name, "status": "passed" if condition else "failed", "detail": detail})
        if not condition:
            raise DemoError(f"{name}: {detail}")

    try:
        validate_marker(paths)
        check("isolation", paths.product.parent == paths.sql.parent and paths.product != paths.sql, "Product and SQL stores are distinct children of the marked demo root.")
        if not paths.runtime.exists():
            raise DemoError("Demo is not running. Run 'python scripts/demo.py start' first.")
        runtime = _read_json(paths.runtime)
        check("runtime", _runtime_is_owned(paths, runtime) and runtime.get("state") == "ready" and _pid_alive(runtime.get("supervisor_pid")), "Owned supervisor metadata is ready and live.")
        backend = f"http://127.0.0.1:{runtime['backend_port']}"
        frontend = f"http://127.0.0.1:{runtime['frontend_port']}"
        with urlopen(backend + "/health", timeout=5) as response:
            health = json.loads(response.read())
        check("backend_health", health.get("status") == "ok" and health.get("engine", {}).get("status") == "open", "Backend and SQL engine report ready.")
        with urlopen(frontend + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
        check("frontend", response.status == 200 and '<div id="root"></div>' in html, "Vite served the STRATA application shell.")

        owner = JsonClient(frontend)
        collaborator = JsonClient(frontend)
        owner_user = owner.request("/api/auth/login", method="POST", body={"email": OWNER["email"], "password": OWNER["password"]})
        collaborator_user = collaborator.request("/api/auth/login", method="POST", body={"email": COLLABORATOR["email"], "password": COLLABORATOR["password"]})
        check("authenticated_login", owner_user["name"] == OWNER["name"] and collaborator_user["name"] == COLLABORATOR["name"], "Both documented demo accounts authenticated independently.")
        workspaces = owner.request(f"/api/users/{owner_user['id']}/workspaces")
        atlas = next((item for item in workspaces if item["name"] == WORKSPACE_NAME), None)
        check("workspace", atlas is not None, f"Found {WORKSPACE_NAME}.")
        projects = owner.request(f"/api/workspaces/{atlas['id']}/projects")
        check("projects", {item["name"] for item in projects} >= set(PROJECTS), "All three showcase projects are visible.")
        tasks = [task for project in projects if project["name"] in PROJECTS for task in owner.request(f"/api/projects/{project['id']}/tasks")]
        check("tasks", len(tasks) >= 7 and {item["status"] for item in tasks} >= {"TODO", "IN_PROGRESS", "DONE"}, "Seeded tasks cover all supported statuses.")
        today = date.today().isoformat()
        due_dates = [item["due_date"] for item in tasks if item["due_date"]]
        check("due_dates", any(item < today for item in due_dates) and today in due_dates and any(item > today for item in due_dates), "Task dates include overdue, today, and upcoming work.")
        mine = collaborator.request(f"/api/my/tasks?workspace_id={atlas['id']}")
        featured = next((item for item in mine["items"] if item["title"] == "Publish responsive landing page"), None)
        check("workspace_assignment", featured is not None, "Collaborator My Tasks contains the featured owner handoff in Atlas Product Team.")
        inbox = collaborator.request("/api/notifications")
        check("notifications", inbox["total"] > 0 and any(item["task_id"] == featured["id"] for item in inbox["items"]), "Collaborator Inbox contains a featured-task notification.")
        activity = owner.request(f"/api/tasks/{featured['id']}/activity")
        check("activity_history", activity["total"] >= 3 and any(item["event_type"] == "ASSIGNEE_CHANGED" for item in activity["items"]), "Featured task retains creation, status, and handoff history.")
        activity_pages = [(task, owner.request(f"/api/tasks/{task['id']}/activity?limit=100")) for task in tasks]
        check(
            "all_activity_identity",
            all(all(event["task_id"] == task["id"] and event["project_id"] == task["project_id"] and event["workspace_id"] == atlas["id"] for event in page["items"]) for task, page in activity_pages),
            "Every Atlas task activity page has the current task, project, and workspace identity.",
        )

        sql = owner.request("/api/sql/profile", method="POST", body={"sql": "SELECT id, title, status FROM demo_work_items WHERE status = 'TODO' ORDER BY id"})
        check("sql_data", sql["kind"] == "query" and sql["row_count"] == 3, "SQL Lab demo rows are queryable.")
        check("sql_profile", sql.get("profile", {}).get("access_path") == "IndexScan", "Equality filtering uses the demo status index.")
        join = owner.request("/api/sql/profile", method="POST", body={"sql": "SELECT demo_projects.name, demo_work_items.title FROM demo_projects INNER JOIN demo_work_items ON demo_projects.id = demo_work_items.project_id ORDER BY demo_work_items.id"})
        check("sql_join", join["kind"] == "query" and join["row_count"] == 6, "Supported two-table INNER JOIN returned all work items.")
        owner.request("/api/auth/logout", method="POST")
        collaborator.request("/api/auth/logout", method="POST")
        result = {"status": "passed", "duration_ms": round((time.monotonic() - started) * 1000), "checks": checks}
    except Exception as exc:
        result = {"status": "failed", "duration_ms": round((time.monotonic() - started) * 1000), "checks": checks, "error": str(exc)}
    _atomic_json(paths.verification, result)
    return result


def reset(paths: DemoPaths) -> dict[str, Any]:
    validate_marker(paths)
    if paths.runtime.exists():
        runtime = _read_json(paths.runtime)
        if _pid_alive(runtime.get("supervisor_pid")) or any(_pid_alive(runtime.get(key)) for key in ("backend_pid", "frontend_pid")):
            raise DemoError("Stop the demo before reset; no files were removed.")
    root = paths.root.resolve()
    expected = (REPO_ROOT / ".verification").resolve()
    if root.parent != expected or (root.name != "demo" and not root.name.startswith("demo-")):
        raise DemoError("Reset target failed the final exact-path safety check.")
    shutil.rmtree(root)
    return {"status": "passed", "message": f"Removed verified demo storage {root}."}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage STRATA's isolated persistent demo.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "verify", "stop"):
        item = subparsers.add_parser(command)
        item.add_argument("--root", type=Path, help=argparse.SUPPRESS)
        if command == "verify":
            item.add_argument("--json", action="store_true", help="Emit machine-readable verification output.")
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    start_parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    start_parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    reset_parser = subparsers.add_parser("reset")
    reset_parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    reset_parser.add_argument("--yes", action="store_true", help="Confirm deletion of verified demo-only storage.")
    serve_parser = subparsers.add_parser("_serve", help=argparse.SUPPRESS)
    serve_parser.add_argument("--root", type=Path, required=True)
    serve_parser.add_argument("--backend-port", type=int, required=True)
    serve_parser.add_argument("--frontend-port", type=int, required=True)
    serve_parser.add_argument("--token", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = demo_paths(args.root)
        if args.command == "_serve":
            return supervise(paths, args.backend_port, args.frontend_port, args.token)
        if args.command == "init":
            result = initialize(paths)
        elif args.command == "start":
            result = start(paths, args.backend_port, args.frontend_port)
        elif args.command == "verify":
            result = verify(paths)
        elif args.command == "stop":
            result = stop(paths)
        elif args.command == "reset":
            if not args.yes:
                raise DemoError("Reset requires --yes and still only accepts a valid demo marker.")
            result = reset(paths)
        else:
            raise DemoError(f"Unknown command: {args.command}")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") == "passed" else 1
    except DemoError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
