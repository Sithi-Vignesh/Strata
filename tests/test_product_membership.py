"""Focused collaborative workspace membership coverage for P1C-B."""

import pytest
from fastapi.testclient import TestClient

from strata_engine import Tuple

from strata_backend.main import create_app


def _register(client: TestClient, name: str, email: str) -> dict[str, object]:
    response = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": "correct horse battery staple",
    })
    assert response.status_code == 201
    return response.json()


def _headers(client: TestClient) -> dict[str, str]:
    return {"cookie": f"strata_session={client.cookies.get('strata_session')}"}


def _team(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    response = client.post("/api/workspaces", json={"name": "Team"}, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_membership_auth_privacy_addition_and_personal_restrictions(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        assert client.post("/api/workspaces/1/members", json={"user_id": 1}).status_code == 401
        owner = _register(client, "Owner", "owner@strata.local")
        owner_headers = _headers(client)
        member = _register(client, "Member", "member@strata.local")
        member_headers = _headers(client)
        team = _team(client, owner_headers)
        assert client.get(f"/api/workspaces/{team['id']}/members", headers=member_headers).status_code == 404
        added = client.post(f"/api/workspaces/{team['id']}/members", json={"user_id": member["id"]}, headers=owner_headers)
        assert added.status_code == 201
        assert added.json() == {"workspace_id": team["id"], "user_id": member["id"], "role": "MEMBER", "name": "Member", "email": "member@strata.local", "account_state": "ACTIVE"}
        assert client.post(f"/api/workspaces/{team['id']}/members", json={"user_id": member["id"]}, headers=owner_headers).status_code == 409
        assert client.post(f"/api/workspaces/{team['id']}/members", json={"user_id": 999}, headers=owner_headers).status_code == 404
        service = app.state.product_service
        inactive = service.create_user("Inactive", "inactive@strata.local")
        inactive_record, inactive_row = service._record_or_not_found("users", inactive.id)
        service._table("users").update(inactive_record, Tuple((
            inactive.id, inactive.name, inactive.email, inactive.password_hash,
            "PENDING_DELETION", inactive.created_at, inactive.deleted_at,
        ), schema=inactive_row.schema))
        assert client.post(f"/api/workspaces/{team['id']}/members", json={"user_id": inactive.id}, headers=owner_headers).status_code == 409
        assert client.post(f"/api/workspaces/{team['id']}/members", json={"user_id": owner["id"]}, headers=member_headers).status_code == 403
        personal_id = client.get(f"/api/users/{owner['id']}/workspaces", headers=owner_headers).json()[0]["id"]
        assert client.post(f"/api/workspaces/{personal_id}/members", json={"user_id": member["id"]}, headers=owner_headers).status_code == 403


def test_transfer_and_remove_unassigns_tasks_preserving_attribution(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        owner = _register(client, "Owner", "owner@strata.local")
        owner_headers = _headers(client)
        member = _register(client, "Member", "member@strata.local")
        member_headers = _headers(client)
        team = _team(client, owner_headers)
        assert client.post(f"/api/workspaces/{team['id']}/members", json={"user_id": member["id"]}, headers=owner_headers).status_code == 201
        assert client.post(f"/api/workspaces/{team['id']}/transfer-ownership", json={"new_owner_user_id": 999}, headers=owner_headers).status_code == 404
        assert client.post(f"/api/workspaces/{team['id']}/transfer-ownership", json={"new_owner_user_id": owner["id"]}, headers=owner_headers).status_code == 409
        assert client.post(f"/api/workspaces/{team['id']}/transfer-ownership", json={"new_owner_user_id": member["id"]}, headers=owner_headers).json() == {"workspace_id": team["id"], "owner_user_id": member["id"], "previous_owner_user_id": owner["id"]}
        members = client.get(f"/api/workspaces/{team['id']}/members", headers=member_headers).json()
        assert {(item["user_id"], item["role"]) for item in members} == {(owner["id"], "MEMBER"), (member["id"], "OWNER")}
        assert client.post(f"/api/workspaces/{team['id']}/transfer-ownership", json={"new_owner_user_id": owner["id"]}, headers=owner_headers).status_code == 403
        assert client.delete(f"/api/workspaces/{team['id']}/members/{member['id']}", headers=member_headers).status_code == 409

        project_one = client.post(f"/api/workspaces/{team['id']}/projects", json={"name": "One"}, headers=member_headers).json()
        project_two = client.post(f"/api/workspaces/{team['id']}/projects", json={"name": "Two"}, headers=member_headers).json()
        task_one = client.post(f"/api/projects/{project_one['id']}/tasks", json={"title": "One", "assignee_user_id": owner["id"]}, headers=member_headers).json()
        task_two = client.post(f"/api/projects/{project_two['id']}/tasks", json={"title": "Two", "assignee_user_id": owner["id"]}, headers=member_headers).json()
        note = client.post(f"/api/tasks/{task_one['id']}/notes", json={"content": "History"}, headers=owner_headers).json()
        assert client.delete(f"/api/workspaces/{team['id']}/members/{owner['id']}", headers=member_headers).status_code == 204
        assert client.get(f"/api/projects/{project_one['id']}", headers=owner_headers).status_code == 404
        service = app.state.product_service
        assert service.get_task(task_one["id"]).assignee_user_id is None
        assert service.get_task(task_two["id"]).assignee_user_id is None
        assert service.get_note(note["id"]).author_user_id == owner["id"]
        assert service.get_task(task_one["id"]).created_by_user_id == member["id"]


def test_membership_compensation_restores_roles_and_assignments(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        owner = _register(client, "Owner", "owner@strata.local")
        owner_headers = _headers(client)
        member = _register(client, "Member", "member@strata.local")
        team = _team(client, owner_headers)
        service = app.state.product_service
        service._create_membership(team["id"], member["id"], "MEMBER")
        original_role_set = service._set_membership_role
        calls = 0

        def fail_second_role_set(record_id, row, role):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("transfer write failed")
            return original_role_set(record_id, row, role)

        monkeypatch.setattr(service, "_set_membership_role", fail_second_role_set)
        with pytest.raises(RuntimeError, match="transfer write failed"):
            service.transfer_workspace_ownership(team["id"], member["id"], actor_user_id=owner["id"])
        assert {(item.user_id, item.role) for item in service.list_workspace_members(team["id"])} == {(owner["id"], "OWNER"), (member["id"], "MEMBER")}

        monkeypatch.setattr(service, "_set_membership_role", original_role_set)
        project = service.create_project(team["id"], "Project", actor_user_id=owner["id"])
        task = service.create_task(project.id, "Assigned", assignee_user_id=member["id"], actor_user_id=owner["id"])

        def fail_member_delete(record_id):
            raise RuntimeError("member delete failed")

        monkeypatch.setattr(service, "_delete_membership", fail_member_delete)
        with pytest.raises(RuntimeError, match="member delete failed"):
            service.remove_workspace_member(team["id"], member["id"], actor_user_id=owner["id"])
        assert service.get_task(task.id).assignee_user_id == member["id"]
        assert any(item.user_id == member["id"] for item in service.list_workspace_members(team["id"]))
