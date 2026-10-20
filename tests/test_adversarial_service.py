"""Bounded failure and contention experiments over isolated product databases."""

from concurrent.futures import Future
from threading import Event, Thread, current_thread

import pytest

from strata_backend.product_bootstrap import initialize_product
from strata_backend.product_service import (
    ProductConflictError,
    ProductDeletionCompensationError,
    ProductNotFoundError,
    ProductPermissionError,
    ProductService,
)
from strata_engine import StrataEngine
from strata_engine.catalog import Table
from strata_engine.concurrency import DatabaseLock


def populate(engine):
    initialize_product(engine)
    service = ProductService(engine)
    owner = service.create_user("Owner", "owner@example.com")
    member = service.create_user("Member", "member@example.com")
    workspace = service.create_workspace("Team", owner.id)
    service.add_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
    project = service.create_project(workspace.id, "Project", actor_user_id=owner.id)
    task = service.create_task(project.id, "Task", assignee_user_id=member.id, actor_user_id=owner.id)
    service.create_note(task.id, owner.id, "First", actor_user_id=owner.id)
    service.create_note(task.id, member.id, "Second", actor_user_id=member.id)
    return service, owner, member, workspace, project, task


def snapshot(engine):
    return {
        name: sorted((row.values for _, row in engine.get_table(name).scan()), key=repr)
        for name in engine.list_tables()
    }


def assert_indexes(engine):
    for name in engine.list_tables():
        table = engine.get_table(name)
        rows = tuple(table.scan())
        for index in table.indexes:
            expected = {(row[index.column_ordinal], rid) for rid, row in rows if row[index.column_ordinal] is not None}
            actual = index.tree.scan_range()
            assert set(actual) == expected
            assert len(actual) == len(expected) == index.tree.entry_count
            index.tree.validate_structure()


@pytest.mark.parametrize("operation,fail_table,fail_call", [
    ("task", "notes", 2),
    ("task", "tasks", 1),
    ("workspace", "workspace_members", 2),
    ("workspace", "workspaces", 1),
])
def test_failed_cascade_restores_children_and_access_after_reopen(tmp_path, monkeypatch, operation, fail_table, fail_call):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        service, owner, member, workspace, project, task = populate(engine)
        if operation == "workspace":
            service.delete_task(task.id, actor_user_id=owner.id)
            service.delete_project(project.id, actor_user_id=owner.id)
        before = snapshot(engine)
        original = Table.delete
        calls = 0

        def fail_once(table, rid):
            nonlocal calls
            if table.name == fail_table:
                calls += 1
                if calls == fail_call:
                    raise OSError("controlled cascade failure")
            return original(table, rid)

        with monkeypatch.context() as patch:
            patch.setattr(Table, "delete", fail_once)
            with pytest.raises(OSError, match="controlled cascade failure"):
                if operation == "task":
                    service.delete_task(task.id, actor_user_id=owner.id)
                else:
                    service.delete_workspace(workspace.id, actor_user_id=owner.id)
        assert snapshot(engine) == before
        assert service.get_workspace(workspace.id, actor_user_id=owner.id) == workspace
        assert service.get_workspace(workspace.id, actor_user_id=member.id) == workspace
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        assert snapshot(reopened) == before
        assert_indexes(reopened)


@pytest.mark.parametrize("fail_table,fail_call", [("tasks", 2), ("workspace_members", 1)])
def test_member_removal_failure_restores_all_assignments_after_reopen(tmp_path, monkeypatch, fail_table, fail_call):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        service, owner, member, workspace, project, task = populate(engine)
        second_project = service.create_project(workspace.id, "Second", actor_user_id=owner.id)
        service.create_task(second_project.id, "Second", assignee_user_id=member.id, actor_user_id=owner.id)
        before = snapshot(engine)
        method = "update" if fail_table == "tasks" else "delete"
        original = getattr(Table, method)
        calls = 0

        def fail_once(table, *args):
            nonlocal calls
            if table.name == fail_table:
                calls += 1
                if calls == fail_call:
                    raise OSError("controlled removal failure")
            return original(table, *args)

        with monkeypatch.context() as patch:
            patch.setattr(Table, method, fail_once)
            with pytest.raises(OSError, match="controlled removal failure"):
                service.remove_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
        assert snapshot(engine) == before
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        assert snapshot(reopened) == before
        assert_indexes(reopened)


@pytest.mark.parametrize("operation", ["task", "workspace"])
def test_cascade_reports_failed_compensation_and_attempts_remaining_rows(tmp_path, monkeypatch, operation):
    with StrataEngine(tmp_path / "product") as engine:
        service, owner, member, workspace, project, task = populate(engine)
        if operation == "workspace":
            service.delete_task(task.id, actor_user_id=owner.id)
            service.delete_project(project.id, actor_user_id=owner.id)
        parent = "tasks" if operation == "task" else "workspaces"
        child = "notes" if operation == "task" else "workspace_members"
        original_delete, original_insert = Table.delete, Table.insert
        restored = []

        def fail_parent(table, rid):
            if table.name == parent:
                raise OSError("controlled parent failure")
            return original_delete(table, rid)

        def fail_first_restore(table, row):
            if table.name == child:
                restored.append(row.values)
                if len(restored) == 1:
                    raise OSError("controlled restore failure")
            return original_insert(table, row)

        with monkeypatch.context() as patch:
            patch.setattr(Table, "delete", fail_parent)
            patch.setattr(Table, "insert", fail_first_restore)
            with pytest.raises(ProductDeletionCompensationError) as caught:
                if operation == "task":
                    service.delete_task(task.id, actor_user_id=owner.id)
                else:
                    service.delete_workspace(workspace.id, actor_user_id=owner.id)
        assert str(caught.value.__cause__) == "controlled parent failure"
        assert len(restored) == 2, "A failed inverse must not skip remaining restoration"
        assert engine.get_table(child).count() == 1
        assert_indexes(engine)


def run_contended(engine, monkeypatch, first, second, pause_object, pause_method):
    """Pause inside the first service operation until the second attempts its lock."""
    paused, attempted = Event(), Event()
    original_enter = DatabaseLock.__enter__
    original_method = getattr(pause_object, pause_method)
    results = [Future(), Future()]

    def enter(lock):
        if lock is engine._lock and current_thread().name == "service-second":
            attempted.set()
        return original_enter(lock)

    def pause(*args, **kwargs):
        value = original_method(*args, **kwargs)
        if current_thread().name == "service-first" and not paused.is_set():
            assert engine._lock._is_owned(), "The service must own the lock across workflow steps"
            paused.set()
            assert attempted.wait(3), "Second operation never attempted the shared lock"
        return value

    def run(index, action):
        try:
            results[index].set_result(action())
        except BaseException as exc:
            results[index].set_exception(exc)

    with monkeypatch.context() as patch:
        patch.setattr(DatabaseLock, "__enter__", enter)
        patch.setattr(pause_object, pause_method, pause)
        jobs = [Thread(target=run, args=(0, first), name="service-first", daemon=True)]
        jobs[0].start()
        try:
            assert paused.wait(3), "First operation never reached the controlled pause"
            jobs.append(Thread(target=run, args=(1, second), name="service-second", daemon=True))
            jobs[1].start()
        finally:
            for job in jobs:
                job.join(8)
                assert not job.is_alive(), "Service worker did not terminate"
    assert attempted.is_set()
    return results


@pytest.mark.parametrize("delete_first", [True, False])
def test_task_delete_and_update_contend_without_orphans(tmp_path, monkeypatch, delete_first):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        a, owner, member, workspace, project, task = populate(engine)
        b = ProductService(engine)
        delete = lambda: a.delete_task(task.id, actor_user_id=owner.id)
        update = lambda: b.update_task(task.id, title="Updated", actor_user_id=member.id)
        first, second = (delete, update) if delete_first else (update, delete)
        first_service = a if delete_first else b
        results = run_contended(engine, monkeypatch, first, second, first_service, "_record_or_not_found")
        results[0].result(timeout=0)
        if delete_first:
            with pytest.raises(ProductNotFoundError):
                results[1].result(timeout=0)
        else:
            results[1].result(timeout=0)
        assert a.list_tasks(project.id, actor_user_id=owner.id) == ()
        assert engine.get_table("notes").count() == 0
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        assert reopened.get_table("tasks").count() == reopened.get_table("notes").count() == 0
        assert_indexes(reopened)


def test_note_creation_contends_at_id_allocation_and_survives_reopen(tmp_path, monkeypatch):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        a, owner, member, workspace, project, task = populate(engine)
        b = ProductService(engine)
        results = run_contended(
            engine, monkeypatch,
            lambda: a.create_note(task.id, owner.id, "Concurrent owner", actor_user_id=owner.id),
            lambda: b.create_note(task.id, member.id, "Concurrent member", actor_user_id=member.id),
            a, "_next_id",
        )
        notes = [result.result(timeout=0) for result in results]
        assert notes[0].id != notes[1].id
        expected = a.list_notes(task.id, actor_user_id=owner.id)
        assert len(expected) == len({note.id for note in expected}) == 4
        assert {note.content for note in expected} == {"First", "Second", "Concurrent owner", "Concurrent member"}
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        assert ProductService(reopened).list_notes(task.id, actor_user_id=member.id) == expected
        assert_indexes(reopened)


@pytest.mark.parametrize("transfer_first", [True, False])
def test_transfer_and_removal_contend_without_invalid_owner_or_assignee(tmp_path, monkeypatch, transfer_first):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        a, owner, member, workspace, project, task = populate(engine)
        b = ProductService(engine)
        transfer = lambda: a.transfer_workspace_ownership(workspace.id, member.id, actor_user_id=owner.id)
        remove = lambda: b.remove_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
        first, second = (transfer, remove) if transfer_first else (remove, transfer)
        first_service, seam = (a, "_set_membership_role") if transfer_first else (b, "_unassign_task")
        results = run_contended(engine, monkeypatch, first, second, first_service, seam)
        results[0].result(timeout=0)
        with pytest.raises(ProductPermissionError if transfer_first else ProductConflictError):
            results[1].result(timeout=0)
        members = a.list_workspace_members(workspace.id, actor_user_id=owner.id)
        assert [m.user_id for m in members if m.role == "OWNER"] == [member.id if transfer_first else owner.id]
        assert a.get_task(task.id).assignee_user_id == (member.id if transfer_first else None)
        expected = snapshot(engine)
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        assert snapshot(reopened) == expected
        assert_indexes(reopened)


@pytest.mark.parametrize("logout_first", [True, False])
def test_expiration_and_logout_contend_without_revoking_reused_session(tmp_path, monkeypatch, logout_first):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        service, owner, member, workspace, project, task = populate(engine)
        now = [1_000]
        a, b = ProductService(engine, clock=lambda: now[0]), ProductService(engine, clock=lambda: now[0])
        old = a.create_session(owner.id)
        now[0] = old.session.expires_at
        expire = lambda: a.find_session_by_token(old.token)
        logout = lambda: b.revoke_session_by_token(old.token)
        first, second = (logout, expire) if logout_first else (expire, logout)
        results = run_contended(engine, monkeypatch, first, second, Table, "delete")
        assert [result.result(timeout=0) for result in results] == [None, None]
        assert engine.get_table("sessions").count() == 0
        replacement = a.create_session(member.id)
        assert replacement.session.id == old.session.id
        b.revoke_session_by_token(old.token)
        assert a.find_session_by_token(old.token) is None
        assert a.find_session_by_token(replacement.token) == replacement.session
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        service = ProductService(reopened, clock=lambda: now[0])
        assert service.find_session_by_token(old.token) is None
        assert service.find_session_by_token(replacement.token) == replacement.session
        assert_indexes(reopened)


def test_failed_transfer_restores_relocated_owner_after_reopen(tmp_path, monkeypatch):
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        service, owner, member, workspace, project, task = populate(engine)
        # 112 OWNER rows (30 bytes + 4-byte slot), 8 MEMBER rows (31 + 4)
        # exactly consume the 4088-byte payload of a real membership page.
        for number in range(111):
            filler = service.create_workspace(f"Filler {number}", owner.id)
            if number < 7:
                service.add_workspace_member(filler.id, member.id, actor_user_id=owner.id)
        before = snapshot(engine)
        members = engine.get_table("workspace_members")
        assert {rid.page_id.value for rid, _ in members.scan()} == {0}
        assert sum(len(members._serializer.serialize(row.values)) + 4 for _, row in members.scan()) == 4088
        old_rid = next(rid for rid, row in members.scan() if row[0] == workspace.id and row[1] == owner.id)
        original_role_set = service._set_membership_role
        promoted = False

        def fail_promotion(rid, row, role):
            nonlocal promoted
            if row[1] == member.id and role == "OWNER" and not promoted:
                promoted = True
                new_rid = next(r for r, value in members.scan() if value[0] == workspace.id and value[1] == owner.id)
                assert new_rid != old_rid, "The demotion must actually relocate"
                raise OSError("controlled promotion failure")
            return original_role_set(rid, row, role)

        with monkeypatch.context() as patch:
            patch.setattr(service, "_set_membership_role", fail_promotion)
            with pytest.raises(OSError, match="controlled promotion failure"):
                service.transfer_workspace_ownership(workspace.id, member.id, actor_user_id=owner.id)
        assert promoted
        assert snapshot(engine) == before
        assert_indexes(engine)
    with StrataEngine(directory) as reopened:
        assert snapshot(reopened) == before
        assert_indexes(reopened)
