"""Deterministic database-lock, directory ownership and integrity experiments."""
from concurrent.futures import Future
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Event, Thread, current_thread

import pytest

from strata_backend.engine_adapter import EngineAdapter
from strata_backend.product_bootstrap import initialize_product
from strata_backend.product_service import ProductConflictError, ProductService
from strata_engine import StrataEngine
from strata_engine.concurrency import DatabaseBusyError, DatabaseInUseError, DatabaseLock


def worker(action):
    result = Future()
    def run():
        try:
            result.set_result(action())
        except BaseException as exc:
            result.set_exception(exc)
    thread = Thread(target=run, daemon=True)
    thread.start()
    return thread, result


def finish(job):
    thread, result = job
    thread.join(8)
    assert not thread.is_alive(), "Worker failed to terminate (possible deadlock)"
    return result.result(timeout=0)


def assert_indexes(engine):
    with engine.operation():
        for name in engine.list_tables():
            table = engine.get_table(name)
            rows = tuple(table.scan())
            for index in table.indexes:
                expected = {(row[index.column_ordinal], rid) for rid, row in rows if row[index.column_ordinal] is not None}
                actual = index.tree.scan_range()
                assert set(actual) == expected
                assert len(actual) == len(expected) == index.tree.entry_count
                index.tree.validate_structure()
                assert all(frame.pin_count == 0 for frame in index.tree._buffer_pool._frames)
            assert all(frame.pin_count == 0 for frame in table.heap_file.buffer_pool_manager._frames)


@pytest.fixture
def product(tmp_path):
    with StrataEngine(tmp_path / "product") as engine:
        initialize_product(engine)
        a, b = ProductService(engine), ProductService(engine)
        owner = a.create_user("Owner", "owner@example.com")
        member = a.create_user("Member", "member@example.com")
        workspace = a.create_workspace("Shared", owner.id)
        a.add_workspace_member_by_email(workspace.id, member.email, actor_user_id=owner.id)
        project = a.create_project(workspace.id, "Project", actor_user_id=owner.id)
        task = a.create_task(project.id, "Task", assignee_user_id=member.id, actor_user_id=owner.id)
        yield engine, a, b, owner, member, workspace, project, task


@pytest.mark.parametrize("route", ["service", "second_service", "sql", "profile", "adapter", "catalog", "table", "scan", "index", "close"])
def test_every_supported_access_path_contends_on_the_same_lock(product, monkeypatch, route):
    engine, a, b, owner, member, workspace, project, task = product
    table = engine.get_table("tasks")
    index = table.indexes[0].tree
    actions = {
        "service": lambda: a.update_task(task.id, status="DONE"),
        "second_service": lambda: b.get_task(task.id),
        "sql": lambda: engine.execute("SELECT id FROM tasks;"),
        "profile": lambda: engine.execute_profiled("SELECT id FROM tasks;"),
        "adapter": lambda: EngineAdapter(engine).execute_profiled("SELECT id FROM tasks;"),
        "catalog": lambda: engine.catalog.get_table("tasks"),
        "table": table.count,
        "scan": lambda: tuple(table.scan()),
        "index": lambda: index.scan_range(),
        "close": engine.close,
    }
    assert a._lock is b._lock is engine._lock is engine.catalog._lock is table._lock is index._lock
    attempted, completed = Event(), Event()
    enter = DatabaseLock.__enter__
    parent = current_thread()
    def observed_enter(lock):
        if lock is engine._lock and current_thread() is not parent:
            attempted.set()
        return enter(lock)
    monkeypatch.setattr(DatabaseLock, "__enter__", observed_enter)
    def action():
        value = actions[route]()
        completed.set()
        return value
    with engine.operation():
        job = worker(action)
        assert attempted.wait(3), "Worker never attempted the shared lock"
        assert not completed.is_set(), "Access bypassed database serialization"
    finish(job)
    assert completed.is_set()


def test_opposite_table_orders_are_serialized_without_deadlock(tmp_path, monkeypatch):
    with StrataEngine(tmp_path / "order") as engine:
        engine.execute("CREATE TABLE left_items (id INTEGER);")
        engine.execute("CREATE TABLE right_items (id INTEGER);")
        engine.create_index("left_id", "left_items", "id")
        engine.create_index("right_id", "right_items", "id")
        held, attempted = Event(), Event()
        enter = DatabaseLock.__enter__
        def observed_enter(lock):
            if current_thread().name == "opposite-order":
                attempted.set()
            return enter(lock)
        monkeypatch.setattr(DatabaseLock, "__enter__", observed_enter)
        def first():
            with engine.operation():
                engine.get_table("left_items").insert([1])
                held.set()
                # Test-only rendezvous: worker B signals BEFORE acquiring the lock.
                assert attempted.wait(3)
                engine.get_table("right_items").insert([1])
        def second():
            assert held.wait(3)
            current_thread().name = "opposite-order"
            with engine.operation():
                engine.get_table("right_items").insert([2])
                engine.get_table("left_items").insert([2])
        first_job, second_job = worker(first), worker(second)
        finish(first_job)
        finish(second_job)
        for name in ("left_items", "right_items"):
            assert [row[0] for _, row in engine.get_table(name).scan()] == [1, 2]
        assert_indexes(engine)
    with StrataEngine(tmp_path / "order") as reopened:
        assert_indexes(reopened)
        assert reopened.get_table("left_items").count() == 2


def test_concurrent_updates_reads_and_ids_across_services(product):
    engine, a, b, owner, member, workspace, project, task = product
    gate = Barrier(3, timeout=5)
    def update(service, changes):
        gate.wait()
        for number in range(15):
            service.update_task(task.id, **changes)
            service.create_task(project.id, "x" * 150 + str(number), description="payload" * 120)
            service.list_tasks(project.id)
    jobs = [worker(lambda: update(a, {"status": "DONE"})), worker(lambda: update(b, {"priority": "HIGH"}))]
    gate.wait()
    for job in jobs:
        finish(job)
    tasks = a.list_tasks(project.id)
    assert len(tasks) == len({item.id for item in tasks}) == 31
    assert a.get_task(task.id).status == "DONE"
    assert a.get_task(task.id).priority == "HIGH"
    assert_indexes(engine)


def test_concurrent_membership_duplicates_and_transfer(product):
    engine, a, b, owner, member, workspace, project, task = product
    third = a.create_user("Third", "third@example.com")
    gate = Barrier(3, timeout=5)
    def add(service):
        gate.wait()
        try:
            service.add_workspace_member_by_email(workspace.id, third.email, actor_user_id=owner.id)
            return "added"
        except ProductConflictError:
            return "duplicate"
    jobs = [worker(lambda: add(a)), worker(lambda: add(b))]
    gate.wait()
    assert sorted(finish(job) for job in jobs) == ["added", "duplicate"]
    gate = Barrier(3, timeout=5)
    def transfer(service, target):
        gate.wait()
        from strata_backend.product_service import ProductPermissionError
        try:
            service.transfer_workspace_ownership(workspace.id, target, actor_user_id=owner.id)
            return "transferred"
        except ProductPermissionError:
            return "denied"
    jobs = [worker(lambda: transfer(a, member.id)), worker(lambda: transfer(b, third.id))]
    gate.wait()
    assert sorted(finish(job) for job in jobs) == ["denied", "transferred"]
    assert sum(item.role == "OWNER" for item in a.list_workspace_members(workspace.id)) == 1
    assert_indexes(engine)


def test_removal_and_assignment_cannot_leave_outside_assignee(product):
    engine, a, b, owner, member, workspace, project, task = product
    gate = Barrier(3, timeout=5)
    def remove():
        gate.wait()
        a.remove_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
    def assign():
        gate.wait()
        from strata_backend.product_service import ProductPermissionError
        try:
            b.update_task(task.id, assignee_user_id=member.id, actor_user_id=owner.id)
        except ProductPermissionError:
            pass
    jobs = [worker(remove), worker(assign)]
    gate.wait()
    for job in jobs:
        finish(job)
    assert a.get_task(task.id).assignee_user_id is None
    assert all(item.user_id != member.id for item in a.list_workspace_members(workspace.id))
    assert_indexes(engine)


def test_exception_and_abandoned_scan_release_lock(product):
    engine, a, b, owner, member, workspace, project, task = product
    from strata_backend.product_service import ProductValidationError
    with pytest.raises(ProductValidationError):
        a.update_task(task.id, status="INVALID")
    scan = engine.get_table("tasks").scan()
    next(scan)  # Keeping the iterator alive must not keep a lock held.
    assert finish(worker(lambda: b.update_task(task.id, status="DONE"))).status == "DONE"
    assert_indexes(engine)


def test_lock_timeout_does_not_release_another_threads_lock():
    lock = DatabaseLock(timeout=0.05)
    def enter():
        with lock:
            return True
    with lock:
        with pytest.raises(DatabaseBusyError):
            finish(worker(enter))
        with lock:  # Nested acquisition remains valid after the other timeout.
            pass
    assert finish(worker(enter))


def test_second_engine_and_process_rejected_then_normal_reopen(tmp_path):
    directory = tmp_path / "owned"
    code = (
        "from strata_engine import StrataEngine; "
        "import sys; StrataEngine(sys.argv[1]).open()"
    )
    with StrataEngine(directory) as engine:
        engine.execute("CREATE TABLE durable (id INTEGER);")
        engine.execute("INSERT INTO durable VALUES (7);")
        with pytest.raises(DatabaseInUseError):
            StrataEngine(directory / ".").open()
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run([sys.executable, "-c", code, str(directory)], capture_output=True, text=True, timeout=8, env=env)
        assert result.returncode != 0
        assert "DatabaseInUseError" in result.stderr
    with StrataEngine(directory) as engine:
        assert engine.execute("SELECT id FROM durable;").rows[0][0] == 7


def test_failed_catalog_open_releases_directory_lease(tmp_path):
    directory = tmp_path / "broken"
    (directory / "catalog").mkdir(parents=True)
    (directory / "catalog" / "tables.db").write_bytes(b"")
    from strata_engine.catalog import CatalogCorruptionError
    for _ in range(2):
        with pytest.raises(CatalogCorruptionError):
            StrataEngine(directory).open()


def test_token_revocation_cannot_delete_a_recycled_session(product, monkeypatch):
    engine, a, b, owner, member, workspace, project, task = product
    old = a.create_session(owner.id)
    looked_up, attempted, recycled = Event(), Event(), Event()
    original_lookup = a.find_session_by_token
    original_enter = DatabaseLock.__enter__
    def enter(lock):
        if current_thread().name == "recycle-session":
            attempted.set()
        return original_enter(lock)
    monkeypatch.setattr(DatabaseLock, "__enter__", enter)
    def lookup(token):
        session = original_lookup(token)
        looked_up.set()
        assert attempted.wait(3)
        # If lookup were outside the enclosing revocation lock, force the
        # dangerous reuse interleaving before returning the old logical ID.
        if not a._lock._is_owned():
            assert recycled.wait(3)
        return session
    monkeypatch.setattr(a, "find_session_by_token", lookup)
    def recycle():
        from strata_backend.product_service import ProductNotFoundError
        assert looked_up.wait(3)
        current_thread().name = "recycle-session"
        with engine.operation():
            try:
                b.revoke_session(old.session.id)
            except ProductNotFoundError:
                pass
            replacement = b.create_session(member.id)
        recycled.set()
        return replacement
    revoke_job = worker(lambda: a.revoke_session_by_token(old.token))
    recycle_job = worker(recycle)
    finish(revoke_job)
    replacement = finish(recycle_job)
    assert replacement.session.id == old.session.id
    assert b.find_session_by_token(replacement.token).user_id == member.id
    b.revoke_session_by_token(old.token)
    assert b.find_session_by_token(replacement.token) is not None
    assert_indexes(engine)


@pytest.mark.parametrize("kind", ["product", "sql"])
def test_api_lock_timeout_is_retryable_503(tmp_path, kind):
    from fastapi.testclient import TestClient
    from strata_backend.main import create_app
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        assert client.post("/api/auth/register", json={"name": "User", "email": "user@example.com", "password": "correct horse battery staple"}).status_code == 201
        engine = app.state.product_service._engine if kind == "product" else app.state.engine_adapter.engine
        engine._lock.timeout = 0.03
        with engine.operation():
            response = client.get("/api/auth/me") if kind == "product" else client.post("/api/sql/profile", json={"sql": "SELECT id FROM tasks;"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "DATABASE_BUSY"
        assert client.get("/api/auth/me").status_code == 200
