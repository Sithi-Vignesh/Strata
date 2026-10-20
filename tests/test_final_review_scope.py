from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from strata_backend.main import create_app
from strata_backend.product_bootstrap import bootstrap_product
from strata_backend.product_service import ProductService, ProductValidationError
from strata_engine.engine import StrataEngine


def _register(client: TestClient, name: str, email: str) -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/register", json={"name": name, "email": email, "password": "Correct-Horse-77"})
    assert response.status_code == 201
    return response.json(), {"cookie": f"strata_session={client.cookies.get('strata_session')}"}


def test_deleted_task_id_is_never_reused_and_activity_survives_restart(tmp_path) -> None:
    directory = tmp_path / "product"
    with StrataEngine(directory) as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        owner = service.create_user("Owner", "owner@history.test")
        first_workspace = service.create_workspace("First", owner.id)
        first_project = service.create_project(first_workspace.id, "Old", actor_user_id=owner.id)
        deleted = service.create_task(first_project.id, "Deleted", actor_user_id=owner.id)
        service.update_task(deleted.id, status="IN_PROGRESS", actor_user_id=owner.id)
        service.delete_task(deleted.id, actor_user_id=owner.id)
        second_workspace = service.create_workspace("Second", owner.id)
        second_project = service.create_project(second_workspace.id, "Current", actor_user_id=owner.id)
        current = service.create_task(second_project.id, "Current", actor_user_id=owner.id)
        assert current.id > deleted.id
        events, _ = service.list_task_activity(current.id, actor_user_id=owner.id)
        assert [(event.workspace_id, event.event_type) for event in events] == [(second_workspace.id, "TASK_CREATED")]
    with StrataEngine(directory) as reopened:
        events, total = ProductService(reopened).list_task_activity(current.id, actor_user_id=owner.id)
        assert total == 1
        assert events[0].task_id == current.id


def test_unambiguous_legacy_reused_task_history_is_scoped_without_deletion(tmp_path) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine, clock=iter(range(10_000, 20_000)).__next__)
        owner = service.create_user("Owner", "owner@legacy.test")
        old_workspace = service.create_workspace("Old", owner.id)
        old_project = service.create_project(old_workspace.id, "Old", actor_user_id=owner.id)
        old_task = service.create_task(old_project.id, "Old", actor_user_id=owner.id)
        service.delete_task(old_task.id, actor_user_id=owner.id)
        new_workspace = service.create_workspace("New", owner.id)
        new_project = service.create_project(new_workspace.id, "New", actor_user_id=owner.id)
        # Reproduce the historical allocator defect explicitly without mutating valid history.
        now = service._now()
        engine.get_table("tasks").insert((old_task.id, new_project.id, "Reused", None, "TODO", "MEDIUM", None, owner.id, now, now))
        service._append_activity(service.get_task(old_task.id), new_workspace.id, owner.id, "TASK_CREATED", {"legacy": True})
        before = engine.get_table("task_activity").count()
        events, total = service.list_task_activity(old_task.id, actor_user_id=owner.id)
        assert total == 1
        assert events[0].workspace_id == new_workspace.id
        assert engine.get_table("task_activity").count() == before


def test_ambiguous_activity_identity_remains_a_validation_error(tmp_path) -> None:
    with StrataEngine(tmp_path / "product") as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        task = service.get_task(1)
        engine.get_table("task_activity").insert((1, task.id, task.project_id, 999, 1, "STATUS_CHANGED", json.dumps({"to": "DONE"}), 1))
        with pytest.raises(ProductValidationError, match="cannot be repaired unambiguously"):
            service.list_task_activity(task.id, actor_user_id=1)


def test_global_and_workspace_scopes_react_to_membership_revocation(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "sql", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        owner, owner_headers = _register(client, "Owner", "owner@scope.test")
        member, member_headers = _register(client, "Member", "member@scope.test")
        first = client.post("/api/workspaces", json={"name": "Alpha"}, headers=owner_headers).json()
        second = client.post("/api/workspaces", json={"name": "Beta"}, headers=owner_headers).json()
        for workspace in (first, second):
            assert client.post(f"/api/workspaces/{workspace['id']}/members", json={"email": member["email"]}, headers=owner_headers).status_code == 201
            project = client.post(f"/api/workspaces/{workspace['id']}/projects", json={"name": f"{workspace['name']} Project"}, headers=owner_headers).json()
            assert client.post(f"/api/projects/{project['id']}/tasks", json={"title": f"{workspace['name']} assigned", "assignee_user_id": member["id"]}, headers=owner_headers).status_code == 201
            assert client.post(f"/api/projects/{project['id']}/tasks", json={"title": f"{workspace['name']} unassigned"}, headers=owner_headers).status_code == 201
        all_tasks = client.get("/api/tasks?sort=title&limit=50", headers=member_headers).json()
        assert {item["workspace_name"] for item in all_tasks["items"]} == {"Alpha", "Beta"}
        alpha_mine = client.get(f"/api/my/tasks?workspace_id={first['id']}", headers=member_headers).json()
        assert [item["title"] for item in alpha_mine["items"]] == ["Alpha assigned"]
        assert client.get("/api/my/tasks", headers=member_headers).status_code == 422
        common = client.get("/api/dashboard", headers=member_headers).json()
        alpha = client.get(f"/api/workspaces/{first['id']}/dashboard", headers=member_headers).json()
        assert common["task_count"] >= 4 and alpha["task_count"] == 2
        assert client.delete(f"/api/workspaces/{second['id']}/members/{member['id']}", headers=owner_headers).status_code == 204
        after = client.get("/api/tasks?limit=50", headers=member_headers).json()
        assert "Beta" not in {item["workspace_name"] for item in after["items"]}
        assert client.get(f"/api/workspaces/{second['id']}/dashboard", headers=member_headers).status_code == 404
        assert client.get(f"/api/my/tasks?workspace_id={second['id']}", headers=member_headers).status_code == 404
