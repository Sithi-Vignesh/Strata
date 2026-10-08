"""Focused authorization coverage for authenticated product resources."""

from fastapi.testclient import TestClient
import pytest

from strata_backend.main import create_app


def _register(client: TestClient, name: str, email: str) -> dict[str, object]:
    response = client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return response.json()


def _session_headers(client: TestClient) -> dict[str, str]:
    return {"cookie": f"strata_session={client.cookies.get('strata_session')}"}


def test_product_resources_require_a_session_and_hide_other_personal_data(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        assert client.get("/api/workspaces/1").status_code == 401
        assert client.post("/api/workspaces", json={"name": "No session"}).status_code == 401

        alice_user = _register(client, "Alice", "alice@strata.local")
        alice_headers = _session_headers(client)
        bob_user = _register(client, "Bob", "bob@strata.local")
        bob_headers = _session_headers(client)
        bob_workspaces = client.get(f"/api/users/{bob_user['id']}/workspaces", headers=bob_headers).json()
        bob_workspace_id = bob_workspaces[0]["id"]
        alice_workspace_id = client.get(f"/api/users/{alice_user['id']}/workspaces", headers=alice_headers).json()[0]["id"]

        assert client.get(f"/api/users/{bob_user['id']}", headers=alice_headers).status_code == 404
        assert client.get(f"/api/users/{bob_user['id']}/workspaces", headers=alice_headers).status_code == 404
        assert client.get(f"/api/workspaces/{bob_workspace_id}", headers=alice_headers).status_code == 404
        assert client.patch(f"/api/workspaces/{alice_workspace_id}", json={"name": "Changed"}, headers=alice_headers).status_code == 403
        assert client.delete(f"/api/workspaces/{alice_workspace_id}", headers=alice_headers).status_code == 403

        workspace = client.post("/api/workspaces", json={"name": "Alice Team"}, headers=alice_headers)
        assert workspace.status_code == 201
        assert workspace.json()["kind"] == "COLLABORATIVE"
        # A client-controlled owner id is not accepted by the public contract.
        assert client.post("/api/workspaces", json={"name": "Spoof", "owner_user_id": bob_user["id"]}, headers=alice_headers).status_code == 422

        project = client.post(f"/api/workspaces/{workspace.json()['id']}/projects", json={"name": "Plan"}, headers=alice_headers)
        assert project.status_code == 201
        assert client.get(f"/api/projects/{project.json()['id']}", headers=bob_headers).status_code == 404
        assert client.patch(f"/api/workspaces/{workspace.json()['id']}", json={"name": "Renamed"}, headers=alice_headers).status_code == 200
        assert alice_user["id"] != bob_user["id"]


def test_note_author_is_session_derived_and_members_have_read_only_note_access(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        owner_user = _register(client, "Owner", "owner@strata.local")
        owner_headers = _session_headers(client)
        member_user = _register(client, "Member", "member@strata.local")
        member_headers = _session_headers(client)
        workspace = client.post("/api/workspaces", json={"name": "Team"}, headers=owner_headers).json()
        service = app.state.product_service
        service._create_membership(workspace["id"], member_user["id"], "MEMBER")
        project = client.post(f"/api/workspaces/{workspace['id']}/projects", json={"name": "Plan"}, headers=owner_headers).json()
        task = client.post(f"/api/projects/{project['id']}/tasks", json={"title": "Task"}, headers=owner_headers).json()

        note = client.post(f"/api/tasks/{task['id']}/notes", json={"content": "Owner note"}, headers=owner_headers)
        assert note.status_code == 201
        assert note.json()["author_user_id"] == owner_user["id"]
        assert client.post(f"/api/tasks/{task['id']}/notes", json={"content": "Spoof", "author_user_id": member_user["id"]}, headers=owner_headers).status_code == 422
        assert client.get(f"/api/notes/{note.json()['id']}", headers=member_headers).status_code == 200
        assert client.patch(f"/api/notes/{note.json()['id']}", json={"content": "Nope"}, headers=member_headers).status_code == 403
        assert client.delete(f"/api/notes/{note.json()['id']}", headers=member_headers).status_code == 403


def test_collaborative_member_permissions_and_creator_delete_fallback(tmp_path) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        owner = _register(client, "Owner", "owner@strata.local")
        owner_headers = _session_headers(client)
        member = _register(client, "Member", "member@strata.local")
        member_headers = _session_headers(client)
        workspace = client.post("/api/workspaces", json={"name": "Team"}, headers=owner_headers).json()
        service = app.state.product_service
        service._create_membership(workspace["id"], member["id"], "MEMBER")

        assert client.get(f"/api/workspaces/{workspace['id']}", headers=member_headers).status_code == 200
        assert client.get(f"/api/workspaces/{workspace['id']}/members", headers=member_headers).status_code == 200
        assert client.patch(f"/api/workspaces/{workspace['id']}", json={"name": "No"}, headers=member_headers).status_code == 403
        assert client.delete(f"/api/workspaces/{workspace['id']}", headers=member_headers).status_code == 403

        owner_project = client.post(f"/api/workspaces/{workspace['id']}/projects", json={"name": "Owner project"}, headers=owner_headers).json()
        member_project = client.post(f"/api/workspaces/{workspace['id']}/projects", json={"name": "Member project"}, headers=member_headers).json()
        assert member_project["created_by_user_id"] == member["id"]
        assert client.patch(f"/api/projects/{owner_project['id']}", json={"name": "Member edit"}, headers=member_headers).status_code == 200
        member_task = client.post(f"/api/projects/{owner_project['id']}/tasks", json={"title": "Member task"}, headers=member_headers).json()
        assert member_task["created_by_user_id"] == member["id"]
        assert client.patch(f"/api/tasks/{member_task['id']}", json={"status": "DONE"}, headers=member_headers).status_code == 200
        assert client.delete(f"/api/projects/{member_project['id']}", headers=owner_headers).status_code == 403
        assert client.delete(f"/api/tasks/{member_task['id']}", headers=owner_headers).status_code == 403

        membership_record, _ = next(
            record for record in service._indexed_records("workspace_members", "user_id", member["id"])
            if record[1][0] == workspace["id"]
        )
        service._table("workspace_members").delete(membership_record)
        assert client.get(f"/api/projects/{member_project['id']}", headers=member_headers).status_code == 404
        assert client.delete(f"/api/projects/{member_project['id']}", headers=owner_headers).status_code == 204
        assert client.delete(f"/api/tasks/{member_task['id']}", headers=owner_headers).status_code == 204


def test_workspace_provisioning_compensates_a_membership_insert_failure(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")
    with TestClient(app) as client:
        user = _register(client, "Owner", "owner@strata.local")
        service = app.state.product_service
        original_insert = service._registration_insert

        def fail_membership(table_name: str, values: tuple[object, ...]):
            if table_name == "workspace_members":
                raise RuntimeError("simulated membership insert failure")
            return original_insert(table_name, values)

        monkeypatch.setattr(service, "_registration_insert", fail_membership)
        with pytest.raises(RuntimeError, match="simulated membership"):
            service.create_workspace("Unprovisioned", user["id"])
        assert [workspace.name for workspace in service.list_workspaces_for_user(user["id"])] == ["My Workspace"]
