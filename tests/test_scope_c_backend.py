"""Scope C collaboration, compatibility, persistence, and concurrency coverage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from strata_backend.main import create_app
from strata_backend.product_bootstrap import PRODUCT_SCHEMAS, PRODUCT_SEED, bootstrap_product
from strata_backend.product_service import ProductNotFoundError, ProductService, ProductValidationError
from strata_engine import StrataEngine


def _register(client: TestClient, name: str, email: str) -> tuple[dict[str, object], dict[str, str]]:
    response = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": "correct horse battery staple",
    })
    assert response.status_code == 201
    headers = {"cookie": f"strata_session={client.cookies.get('strata_session')}"}
    return response.json(), headers


def test_due_dates_my_tasks_activity_handoff_and_notifications_api(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "sql", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        owner, owner_headers = _register(client, "Owner", "owner@example.test")
        member, member_headers = _register(client, "Member", "member@example.test")
        outsider, outsider_headers = _register(client, "Outsider", "outsider@example.test")

        workspace = client.post("/api/workspaces", json={"name": "Team"}, headers=owner_headers).json()
        added = client.post(
            f"/api/workspaces/{workspace['id']}/members",
            json={"email": member["email"]}, headers=owner_headers,
        )
        assert added.status_code == 201
        project = client.post(
            f"/api/workspaces/{workspace['id']}/projects",
            json={"name": "Delivery"}, headers=owner_headers,
        ).json()
        created = client.post(
            f"/api/projects/{project['id']}/tasks",
            json={"title": "Ship Scope C", "assignee_user_id": member["id"], "due_date": "2027-02-28"},
            headers=owner_headers,
        )
        assert created.status_code == 201
        task = created.json()
        assert task["due_date"] == "2027-02-28"
        assert client.post(
            f"/api/projects/{project['id']}/tasks",
            json={"title": "Bad date", "due_date": "2027-02-29"}, headers=owner_headers,
        ).status_code == 422

        mine = client.get(f"/api/my/tasks?workspace_id={workspace['id']}&sort=due_asc&limit=10", headers=member_headers)
        assert mine.status_code == 200
        assert mine.json()["total"] == 1
        mine_item = mine.json()["items"][0]
        assert mine_item["id"] == task["id"]
        assert mine_item["workspace_id"] == workspace["id"]
        assert mine_item["workspace_name"] == "Team"
        assert mine_item["project_name"] == "Delivery"
        assert client.get(f"/api/my/tasks?workspace_id={workspace['id']}", headers=outsider_headers).status_code == 404

        assert client.patch(
            f"/api/tasks/{task['id']}", json={"assignee_user_id": None}, headers=owner_headers,
        ).status_code == 200
        handed_off = client.patch(
            f"/api/tasks/{task['id']}",
            json={"assignee_user_id": member["id"], "handoff_note": "Start with the release checklist."},
            headers=owner_headers,
        )
        assert handed_off.status_code == 200
        invalid_handoff = client.patch(
            f"/api/tasks/{task['id']}", json={"handoff_note": "No reassignment"}, headers=owner_headers,
        )
        assert invalid_handoff.status_code == 422

        activity = client.get(f"/api/tasks/{task['id']}/activity", headers=member_headers)
        assert activity.status_code == 200
        assert {item["event_type"] for item in activity.json()["items"]} >= {"TASK_CREATED", "ASSIGNEE_CHANGED"}
        assert any(item["details"].get("handoff_note") for item in activity.json()["items"] if item["details"])
        assert client.get(f"/api/tasks/{task['id']}/activity", headers=outsider_headers).status_code == 404

        notifications = client.get("/api/notifications", headers=member_headers).json()
        assert notifications["total"] >= 3
        assert {item["event_type"] for item in notifications["items"]} >= {"WORKSPACE_ADDED", "TASK_ASSIGNED", "TASK_HANDOFF"}
        notification_id = notifications["items"][0]["id"]
        assert client.patch(
            f"/api/notifications/{notification_id}", json={"is_read": True}, headers=outsider_headers,
        ).status_code == 404
        assert client.patch(
            f"/api/notifications/{notification_id}", json={"is_read": True}, headers=member_headers,
        ).json()["is_read"] is True
        assert client.post("/api/notifications/mark-all-read", headers=member_headers).status_code == 200
        assert client.get("/api/notifications/unread-count", headers=member_headers).json() == {"unread_count": 0}
        assert client.delete(f"/api/notifications/{notification_id}", headers=member_headers).status_code == 204

        assert client.delete(
            f"/api/workspaces/{workspace['id']}/members/{member['id']}", headers=owner_headers,
        ).status_code == 204
        assert client.get(f"/api/my/tasks?workspace_id={workspace['id']}", headers=member_headers).status_code == 404
        assert client.get(f"/api/tasks/{task['id']}/activity", headers=member_headers).status_code == 404
        remaining = client.get("/api/notifications", headers=member_headers).json()["items"]
        assert [item["event_type"] for item in remaining] == ["WORKSPACE_REMOVED"]


def test_due_date_activity_and_notifications_survive_restart(tmp_path) -> None:
    product_dir = tmp_path / "product"
    app_args = {"data_dir": tmp_path / "sql", "product_data_dir": product_dir}
    with TestClient(create_app(**app_args)) as client:
        user, headers = _register(client, "Persistent", "persistent@example.test")
        workspace_id = client.get(f"/api/users/{user['id']}/workspaces", headers=headers).json()[0]["id"]
        project_id = client.get(f"/api/workspaces/{workspace_id}/projects", headers=headers).json()[0]["id"]
        task = client.post(
            f"/api/projects/{project_id}/tasks", json={"title": "Persist", "due_date": "2030-01-02"}, headers=headers,
        ).json()
    with TestClient(create_app(**app_args)) as client:
        login = client.post("/api/auth/login", json={
            "email": "persistent@example.test", "password": "correct horse battery staple",
        })
        assert login.status_code == 200
        assert client.get(f"/api/tasks/{task['id']}").json()["due_date"] == "2030-01-02"
        assert client.get(f"/api/tasks/{task['id']}/activity").json()["total"] == 1


def test_legacy_database_is_extended_without_rewriting_task_rows(tmp_path) -> None:
    database = tmp_path / "legacy"
    legacy_tables = ("users", "workspaces", "workspace_members", "projects", "tasks", "notes", "sessions")
    with StrataEngine(database) as engine:
        for name in legacy_tables:
            table = engine.create_table(name, PRODUCT_SCHEMAS[name])
            for values in PRODUCT_SEED[name]:
                table.insert(values)
        original_tasks = tuple(row.values for _, row in engine.get_table("tasks").scan())
        bootstrap_product(engine)
        assert tuple(row.values for _, row in engine.get_table("tasks").scan()) == original_tasks
        assert ProductService(engine).get_task(1).due_date is None
        assert engine.has_table("task_due_dates")
        assert engine.has_table("task_activity")
        assert engine.has_table("notifications")


def test_failed_activity_write_compensates_task_mutation(tmp_path, monkeypatch) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        task = service.create_task(1, "Before", due_date="2028-01-01")
        original = service.get_task(task.id)
        original_activity_count = engine.get_table("task_activity").count()

        def fail_activity(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("injected activity failure")

        monkeypatch.setattr(service, "_append_activity", fail_activity)
        with pytest.raises(RuntimeError, match="injected"):
            service.update_task(task.id, title="After", due_date="2028-02-02")
        assert service.get_task(task.id) == original
        assert engine.get_table("task_activity").count() == original_activity_count


def test_concurrent_task_updates_are_serialized_without_hanging(tmp_path) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        task = service.create_task(1, "Concurrent")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda number: service.update_task(task.id, title=f"Edit {number}"), range(24)))
        assert len(results) == 24
        assert service.get_task(task.id).title.startswith("Edit ")
        events, total = service.list_task_activity(task.id, actor_user_id=1, limit=100)
        assert total == 25
        assert len(events) == 25


def test_query_validation_and_bounded_pagination(tmp_path) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        service.create_task(1, "Alpha", due_date="2028-01-02", priority="HIGH", assignee_user_id=1)
        service.create_task(1, "Beta", due_date="2028-01-01", priority="LOW", assignee_user_id=1)
        page, total = service.list_assigned_tasks(actor_user_id=1, query="a", sort="due_asc", limit=1)
        assert total >= 2 and len(page) == 1 and page[0].task.title == "Beta"
        with pytest.raises(ProductValidationError):
            service.list_assigned_tasks(actor_user_id=1, limit=101)
        with pytest.raises(ProductValidationError):
            service.list_tasks(1, sort="arbitrary")


def test_deleted_task_history_is_retained_until_workspace_deletion(tmp_path) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        user = service.create_user("Lifecycle", "lifecycle@example.test")
        workspace = service.create_workspace("Lifecycle Team", user.id)
        project = service.create_project(workspace.id, "Lifecycle Project", actor_user_id=user.id)
        task = service.create_task(project.id, "Disposable", actor_user_id=user.id)
        service.delete_task(task.id, actor_user_id=user.id)
        events, total = service.list_task_activity(task.id, actor_user_id=user.id)
        assert total == 2
        assert events[0].event_type == "TASK_DELETED"
        service.delete_project(project.id, actor_user_id=user.id)
        assert service.list_task_activity(task.id, actor_user_id=user.id)[1] == 2
        service.delete_workspace(workspace.id, actor_user_id=user.id)
        assert not tuple(
            row for _, row in engine.get_table("task_activity").scan()
            if row[3] == workspace.id
        )


def test_notification_and_revocation_races_follow_the_serialization_boundary(tmp_path) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        owner = service.create_user("Race Owner", "race-owner@example.test")
        member = service.create_user("Race Member", "race-member@example.test")
        workspace = service.create_workspace("Race Team", owner.id)
        service.add_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
        project = service.create_project(workspace.id, "Race Project", actor_user_id=owner.id)
        task = service.create_task(project.id, "Race Task", assignee_user_id=member.id, actor_user_id=owner.id)

        def edit(number: int) -> None:
            service.update_task(task.id, title=f"Concurrent notification {number}", actor_user_id=owner.id)

        def read_and_mark() -> None:
            for _ in range(12):
                service.list_notifications(actor_user_id=member.id)
                service.mark_all_notifications_read(actor_user_id=member.id)

        with ThreadPoolExecutor(max_workers=8) as pool:
            edit_jobs = [pool.submit(edit, number) for number in range(12)]
            read_job = pool.submit(read_and_mark)
            for job in edit_jobs:
                job.result(timeout=10)
            read_job.result(timeout=10)
        notifications, total = service.list_notifications(actor_user_id=member.id, limit=100)
        assert total == 14
        assert len({item.id for item in notifications}) == total

        barrier = Barrier(2, timeout=5)

        def revoke() -> None:
            barrier.wait()
            service.remove_workspace_member(workspace.id, member.id, actor_user_id=owner.id)

        def read_during_revoke() -> object:
            barrier.wait()
            try:
                return service.list_task_activity(task.id, actor_user_id=member.id)
            except ProductNotFoundError:
                return "revoked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            revoke_job = pool.submit(revoke)
            read_job = pool.submit(read_during_revoke)
            revoke_job.result(timeout=10)
            race_result = read_job.result(timeout=10)
            assert race_result == "revoked" or isinstance(race_result, tuple)
        visible, _ = service.list_notifications(actor_user_id=member.id, limit=100)
        assert [item.event_type for item in visible] == ["WORKSPACE_REMOVED"]

        service.delete_task(task.id, actor_user_id=owner.id)
        service.delete_project(project.id, actor_user_id=owner.id)
        deletion_barrier = Barrier(2, timeout=5)

        def delete_workspace() -> None:
            deletion_barrier.wait()
            service.delete_workspace(workspace.id, actor_user_id=owner.id)

        def read_during_delete() -> object:
            deletion_barrier.wait()
            try:
                return service.list_task_activity(task.id, actor_user_id=owner.id)
            except ProductNotFoundError:
                return "deleted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            delete_job = pool.submit(delete_workspace)
            activity_job = pool.submit(read_during_delete)
            delete_job.result(timeout=10)
            activity_result = activity_job.result(timeout=10)
            assert activity_result == "deleted" or isinstance(activity_result, tuple)
        assert not tuple(
            row for _, row in engine.get_table("task_activity").scan()
            if row[3] == workspace.id
        )
