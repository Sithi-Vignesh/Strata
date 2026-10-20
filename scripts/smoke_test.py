r"""Run real HTTP acceptance scenarios on isolated databases; never touches data/.

Usage: .\.venv\Scripts\python.exe scripts/smoke_test.py
Requires the existing project dev dependencies (httpx and pytest).
"""
from contextlib import contextmanager
from pathlib import Path
import socket
import shutil
import time
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Thread
from concurrent.futures import Future

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx
import uvicorn
from strata_backend.main import create_app
from strata_engine import StrataEngine

PASSWORD = "strata smoke password 2026"


@contextmanager
def running_server(directory, port=0):
    """Use a real loopback socket with graceful ASGI lifespan shutdown."""
    ready = Event()
    failure = Future()
    app = create_app(data_dir=directory / "demo", product_data_dir=directory / "product", session_cookie_secure=False)
    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()
    server = Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False))
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    port = sock.getsockname()[1]
    def serve():
        try:
            server.run(sockets=[sock])
            failure.set_result(None)
        except BaseException as exc:
            failure.set_exception(exc)
        finally:
            ready.set()
    thread = Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert ready.wait(15), "Backend startup timed out"
        if failure.done():
            failure.result()
        assert server.started, "Backend failed to start"
        yield f"http://127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()
        assert not thread.is_alive(), "Backend did not stop gracefully"
        failure.result(timeout=0)


def request(client, method, url, expected=200, **kwargs):
    response = client.request(method, url, **kwargs)
    # Do not include cookie headers, tokens or passwords in diagnostics.
    assert response.status_code == expected, f"{method} {url}: expected {expected}, got {response.status_code}: {response.text[:300]}"
    return None if expected == 204 else response.json()


def register(client, name):
    return request(client, "POST", "/api/auth/register", 201, json={"name": name, "email": f"{name.lower()}@example.com", "password": PASSWORD})


def login(client, name):
    return request(client, "POST", "/api/auth/login", json={"email": f"{name.lower()}@example.com", "password": PASSWORD})


def concurrent_updates(url, a, b, task_id):
    barrier = Barrier(3, timeout=5)
    jobs = []
    for cookies, patch in ((a.cookies, {"status": "DONE"}), (b.cookies, {"priority": "HIGH"})):
        future = Future()
        def update(cookies=cookies, patch=patch, future=future):
            try:
                with httpx.Client(base_url=url, cookies=cookies, timeout=10, trust_env=False) as client:
                    barrier.wait()
                    for _ in range(5):
                        request(client, "PATCH", f"/api/tasks/{task_id}", json=patch)
                        request(client, "GET", f"/api/tasks/{task_id}")
                future.set_result(None)
            except BaseException as exc:
                future.set_exception(exc)
        thread = Thread(target=update, daemon=True)
        thread.start()
        jobs.append((thread, future))
    barrier.wait()
    for thread, future in jobs:
        thread.join(15)
        assert not thread.is_alive(), "Concurrent HTTP worker did not finish"
        future.result(timeout=0)
    final = request(a, "GET", f"/api/tasks/{task_id}")
    assert (final["status"], final["priority"]) == ("DONE", "HIGH")


def verify_indexes(engine):
    with engine.operation():
        for name in engine.list_tables():
            table = engine.get_table(name)
            rows = tuple(table.scan())
            for index in table.indexes:
                expected = {(row[index.column_ordinal], rid) for rid, row in rows if row[index.column_ordinal] is not None}
                actual = index.tree.scan_range()
                assert set(actual) == expected and len(actual) == len(expected), f"Index mismatch: {index.name}"
                index.tree.validate_structure()


def run():
    with TemporaryDirectory(prefix="strata-smoke-") as temporary:
        directory = Path(temporary)
        with running_server(directory) as (url, app):
            with httpx.Client(base_url=url, timeout=10, trust_env=False) as a, httpx.Client(base_url=url, timeout=10, trust_env=False) as b, httpx.Client(base_url=url, timeout=10, trust_env=False) as c:
                request(a, "GET", "/health")
                request(a, "GET", "/api/workspaces/1", 401)
                owner, member, outsider = register(a, "Alice"), register(b, "Bob"), register(c, "Charlie")
                request(a, "POST", "/api/auth/logout", 403, headers={"Origin": "http://127.0.0.1:1", "Sec-Fetch-Site": "same-site"})
                assert request(a, "GET", "/api/auth/me")["id"] == owner["id"]
                request(a, "POST", "/api/auth/logout", 204, headers={"Origin": url})
                request(b, "POST", "/api/auth/logout", 204)
                assert login(a, "Alice")["id"] == owner["id"]
                assert login(b, "Bob")["id"] == member["id"]
                assert request(a, "GET", "/api/auth/me")["id"] == owner["id"]
                assert request(b, "GET", "/api/auth/me")["id"] == member["id"]
                assert a.cookies.get("strata_session") != b.cookies.get("strata_session")
                print("PASS - Authentication and independent sessions", flush=True)

                workspace = request(a, "POST", "/api/workspaces", 201, json={"name": "Smoke team"})
                wid = workspace["id"]
                membership = request(a, "POST", f"/api/workspaces/{wid}/members", 201, json={"email": " Bob@EXAMPLE.COM "})
                assert membership["user_id"] == member["id"] and membership["role"] == "MEMBER"
                assert wid in [item["id"] for item in request(b, "GET", f"/api/users/{member['id']}/workspaces")]
                assert request(b, "GET", f"/api/workspaces/{wid}/projects") == []
                print("PASS - Email-based collaboration", flush=True)

                project = request(a, "POST", f"/api/workspaces/{wid}/projects", 201, json={"name": "Release"})
                pid = project["id"]
                assert request(b, "GET", f"/api/workspaces/{wid}/projects")[0]["id"] == pid
                print("PASS - Project creation", flush=True)
                task = request(a, "POST", f"/api/projects/{pid}/tasks", 201, json={
                    "title": "Ship Strata", "assignee_user_id": member["id"], "due_date": "2027-01-15",
                })
                tid = task["id"]
                assert request(b, "GET", f"/api/tasks/{tid}")["due_date"] == "2027-01-15"
                mine = request(b, "GET", f"/api/my/tasks?workspace_id={wid}&sort=due_asc&limit=10")
                assert mine["total"] == 1 and mine["items"][0]["workspace_id"] == wid
                activity = request(b, "GET", f"/api/tasks/{tid}/activity")
                assert activity["total"] == 1 and activity["items"][0]["event_type"] == "TASK_CREATED"
                notifications = request(b, "GET", "/api/notifications")
                assert {item["event_type"] for item in notifications["items"]} >= {"WORKSPACE_ADDED", "TASK_ASSIGNED"}
                assert request(b, "GET", "/api/notifications/unread-count")["unread_count"] >= 2
                request(b, "POST", "/api/notifications/mark-all-read")
                assert request(b, "GET", "/api/notifications/unread-count")["unread_count"] == 0
                print("PASS - Due dates, My Tasks, activity and persistent notifications", flush=True)
                print("PASS - Task assignment", flush=True)
                request(b, "PATCH", f"/api/tasks/{tid}", json={"status": "IN_PROGRESS"})
                assert request(a, "GET", f"/api/tasks/{tid}")["status"] == "IN_PROGRESS"
                print("PASS - Cross-user task update", flush=True)

                note = request(b, "POST", f"/api/tasks/{tid}/notes", 201, json={"content": "Bob's persisted note"})
                nid = note["id"]
                assert request(a, "GET", f"/api/tasks/{tid}/notes")[0]["author_user_id"] == member["id"]
                request(b, "PATCH", f"/api/notes/{nid}", json={"content": "Reviewed by Bob"})
                assert request(a, "GET", f"/api/notes/{nid}")["content"] == "Reviewed by Bob"
                print("PASS - Shared notes and author attribution", flush=True)

                personal = request(a, "GET", f"/api/users/{owner['id']}/workspaces")[0]
                request(b, "GET", f"/api/workspaces/{personal['id']}", 404)
                for endpoint in (f"/api/workspaces/{wid}", f"/api/projects/{pid}", f"/api/tasks/{tid}", f"/api/notes/{nid}"):
                    request(c, "GET", endpoint, 404)
                request(b, "POST", f"/api/workspaces/{wid}/members", 403, json={"email": outsider["email"]})
                request(c, "POST", f"/api/workspaces/{wid}/members", 404, json={"email": outsider["email"]})
                request(a, "PATCH", f"/api/tasks/{tid}", 403, json={"assignee_user_id": outsider["id"]})
                request(a, "PATCH", f"/api/notes/{nid}", 403, json={"content": "Not my note"})
                request(a, "POST", f"/api/workspaces/{wid}/members", 422, json={"email": member["email"], "user_id": member["id"]})
                print("PASS - Authorization isolation", flush=True)

                concurrent_updates(url, a, b, tid)
                verify_indexes(app.state.product_service._engine)
                print("PASS - Concurrent HTTP updates and index integrity", flush=True)
                request(a, "DELETE", f"/api/workspaces/{wid}/members/{member['id']}", 204)
                request(b, "GET", f"/api/workspaces/{wid}", 404)
                request(b, "GET", f"/api/tasks/{tid}", 404)
                assert request(a, "GET", f"/api/tasks/{tid}")["assignee_user_id"] is None
                assert request(a, "GET", f"/api/notes/{nid}")["author_user_id"] == member["id"]
                print("PASS - Membership removal and assignment cleanup", flush=True)
                request(a, "POST", "/api/auth/logout", 204)
                request(a, "GET", "/api/auth/me", 401)
                login(a, "Alice")
                assert request(a, "GET", f"/api/tasks/{tid}")["status"] == "DONE"
                cookies = httpx.Cookies(a.cookies)

        # A new engine and app lifecycle reopens the same isolated data files.
        with running_server(directory) as (url, app):
            with httpx.Client(base_url=url, cookies=cookies, timeout=10, trust_env=False) as a:
                assert request(a, "GET", "/api/auth/me")["id"] == owner["id"]
                assert request(a, "GET", f"/api/workspaces/{wid}")["name"] == "Smoke team"
                assert request(a, "GET", f"/api/projects/{pid}")["name"] == "Release"
                task = request(a, "GET", f"/api/tasks/{tid}")
                assert (task["status"], task["priority"], task["assignee_user_id"]) == ("DONE", "HIGH", None)
                assert task["due_date"] == "2027-01-15"
                assert request(a, "GET", f"/api/tasks/{tid}/activity")["total"] >= 3
                assert request(a, "GET", f"/api/notes/{nid}")["content"] == "Reviewed by Bob"
                verify_indexes(app.state.product_service._engine)
        with StrataEngine(directory / "product") as engine:
            verify_indexes(engine)
        print("PASS - Persistence across logout, login, backend restart and database reopen", flush=True)

    # Controlled contention at the lock boundary complements the live HTTP race.
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_concurrency.py"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, "Deadlock experiments failed:\n" + result.stdout + result.stderr
    print("PASS - Controlled concurrency/deadlock prevention experiments", flush=True)
    print("All automated smoke scenarios passed. Human browser acceptance is tracked separately in docs/adversarial-hardening.md.", flush=True)


def verify_frontend():
    """Start the real Vite dev server and check its same-origin backend proxy."""
    node = shutil.which("node")
    assert node is not None, "Node.js is required for --frontend"
    vite = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    assert vite.is_file(), "Install frontend dependencies first (npm ci)"
    with TemporaryDirectory(prefix="strata-web-smoke-") as temporary:
        directory = Path(temporary)
        with running_server(directory, port=8000):
            with (directory / "vite.log").open("w+") as log:
                process = subprocess.Popen([node, str(vite), "--host", "127.0.0.1", "--port", "5173", "--strictPort"], cwd=ROOT / "frontend", stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    deadline = time.monotonic() + 15
                    with httpx.Client(base_url="http://127.0.0.1:5173", headers={"Origin": "http://127.0.0.1:5173"}, timeout=3, trust_env=False) as client:
                        while True:
                            assert process.poll() is None, "Vite exited before readiness; check port 5173"
                            try:
                                page = client.get("/")
                                if page.status_code == 200:
                                    break
                            except httpx.TransportError:
                                pass
                            assert time.monotonic() < deadline, "Vite startup timed out"
                            time.sleep(0.1)  # Readiness polling, not a concurrency experiment.
                        assert '/src/main.tsx' in page.text
                        assert client.get("/src/main.tsx").status_code == 200
                        assert client.get("/src/pages/ProjectsPage.tsx").status_code == 200
                        assert request(client, "GET", "/health")["status"] == "ok"
                        registered = register(client, "Frontend")
                        assert request(client, "GET", "/api/auth/me")["id"] == registered["id"]
                        request(client, "POST", "/api/auth/logout", 204)
                        request(client, "GET", "/api/auth/me", 401)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                log.seek(0)
                assert "error" not in log.read().lower(), "Vite reported an error"
    print("PASS - Frontend startup, module serving and authenticated API proxy", flush=True)


if __name__ == "__main__":
    try:
        run()
        if "--frontend" in sys.argv[1:]:
            verify_frontend()
    except Exception as exc:
        print(f"FAIL - {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
