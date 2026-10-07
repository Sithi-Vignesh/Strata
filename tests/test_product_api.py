"""HTTP boundary coverage for the B3 ProductService API."""

from fastapi.testclient import TestClient

from strata_backend.main import create_app


def _app(tmp_path):
    return create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")


def _detail(response):
    return response.json()["detail"]


def test_product_storage_is_created_only_during_lifespan(tmp_path) -> None:
    product_database = tmp_path / "product"
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=product_database)

    assert not product_database.exists()
    with TestClient(app) as client:
        assert product_database.is_dir()
        assert client.get("/api/users/1").status_code == 200


def test_product_api_user_workspace_and_health_contract(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "service": "strata_backend",
            "engine": {"name": "StrataEngine", "status": "open", "initialized": True},
        }

        created = client.post("/api/users", json={"name": "Ada", "email": "ada@strata.local"})
        assert created.status_code == 201
        assert created.json() == {
            "id": 2, "name": "Ada", "email": "ada@strata.local",
            "account_state": "ACTIVE", "created_at": created.json()["created_at"], "deleted_at": None,
        }
        assert client.get("/api/users/2").json() == created.json()
        assert client.patch("/api/users/2", json={"name": "Ada Lovelace"}).json()["name"] == "Ada Lovelace"

        duplicate = client.post("/api/users", json={"name": "Again", "email": "ADA@STRATA.LOCAL"})
        assert duplicate.status_code == 409
        assert _detail(duplicate)["code"] == "PRODUCT_CONFLICT"
        missing = client.get("/api/users/999")
        assert missing.status_code == 404
        assert _detail(missing)["code"] == "PRODUCT_NOT_FOUND"
        assert client.post("/api/users", json={"name": "Extra", "email": "extra@strata.local", "role": "X"}).status_code == 422

        workspace = client.post("/api/workspaces", json={"name": "Ada Space", "owner_user_id": 2})
        assert workspace.status_code == 201
        assert client.get(f"/api/workspaces/{workspace.json()['id']}").json() == workspace.json()
        assert client.get("/api/users/2/workspaces").json() == [workspace.json()]
        assert client.patch(f"/api/workspaces/{workspace.json()['id']}", json={"name": "Ada Workspace"}).status_code == 200
        members = client.get(f"/api/workspaces/{workspace.json()['id']}/members")
        assert members.json() == [{"workspace_id": 2, "user_id": 2, "role": "OWNER"}]
        deleted = client.delete(f"/api/workspaces/{workspace.json()['id']}")
        assert deleted.status_code == 204 and deleted.content == b""
        cors = client.options(
            "/api/users/2",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PATCH"},
        )
        assert cors.status_code == 200
        assert "PATCH" in cors.headers["access-control-allow-methods"]


def test_project_routes_patch_null_and_dependency_conflict(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        created = client.post("/api/workspaces/1/projects", json={"name": "HTTP project", "description": "Initial"})
        assert created.status_code == 201
        project_id = created.json()["id"]
        assert client.get("/api/workspaces/1/projects").json()[-1]["id"] == project_id
        assert client.get(f"/api/projects/{project_id}").json() == created.json()
        assert client.patch(f"/api/projects/{project_id}", json={"name": "Renamed"}).json()["description"] == "Initial"
        cleared = client.patch(f"/api/projects/{project_id}", json={"description": None})
        assert cleared.status_code == 200 and cleared.json()["description"] is None
        assert client.post("/api/workspaces/1/projects", json={"name": "No", "workspace_id": 1}).status_code == 422
        deleted = client.delete(f"/api/projects/{project_id}")
        assert deleted.status_code == 204 and deleted.content == b""

        blocked = client.delete("/api/projects/1")
        assert blocked.status_code == 409
        assert _detail(blocked)["code"] == "PRODUCT_CONFLICT"
        workspace_blocked = client.delete("/api/workspaces/1")
        assert workspace_blocked.status_code == 409
        assert _detail(workspace_blocked)["code"] == "PRODUCT_CONFLICT"


def test_task_note_routes_patch_semantics_permissions_and_cascade(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        task = client.post("/api/projects/1/tasks", json={"title": "HTTP task", "description": "Initial", "assignee_user_id": 1})
        assert task.status_code == 201
        task_id = task.json()["id"]
        assert client.get("/api/projects/1/tasks").json()[-1]["id"] == task_id
        assert client.get(f"/api/tasks/{task_id}").json()["title"] == "HTTP task"
        assert client.patch(f"/api/tasks/{task_id}", json={}).json()["description"] == "Initial"
        assert client.patch(f"/api/tasks/{task_id}", json={"description": None}).json()["description"] is None
        assert client.patch(f"/api/tasks/{task_id}", json={"assignee_user_id": None}).json()["assignee_user_id"] is None
        assert client.patch(f"/api/tasks/{task_id}", json={"status": "IN_PROGRESS"}).json()["status"] == "IN_PROGRESS"
        assert client.patch(f"/api/tasks/{task_id}", json={"created_by_user_id": 1}).status_code == 422
        assert client.patch(f"/api/tasks/{task_id}", json={"created_at": 1}).status_code == 422
        invalid_status = client.patch(f"/api/tasks/{task_id}", json={"status": "BLOCKED"})
        assert invalid_status.status_code == 422
        assert _detail(invalid_status)["code"] == "PRODUCT_VALIDATION_ERROR"
        invalid_priority = client.patch(f"/api/tasks/{task_id}", json={"priority": "URGENT"})
        assert invalid_priority.status_code == 422
        assert _detail(invalid_priority)["code"] == "PRODUCT_VALIDATION_ERROR"
        assert client.patch(f"/api/tasks/{task_id}", json={"title": None}).status_code == 422
        assert client.post("/api/projects/1/tasks", json={"title": "No", "project_id": 1}).status_code == 422

        other = client.post("/api/users", json={"name": "Other", "email": "other@strata.local"}).json()
        denied = client.patch(f"/api/tasks/{task_id}", json={"assignee_user_id": other["id"]})
        assert denied.status_code == 403
        assert _detail(denied)["code"] == "PRODUCT_PERMISSION_DENIED"

        note = client.post("/api/tasks/{}/notes".format(task_id), json={"author_user_id": 1, "content": "HTTP note"})
        assert note.status_code == 201
        note_id = note.json()["id"]
        assert client.get(f"/api/tasks/{task_id}/notes").json()[-1]["id"] == note_id
        assert client.get(f"/api/notes/{note_id}").json()["content"] == "HTTP note"
        assert client.patch(f"/api/notes/{note_id}", json={"content": "Updated"}).json()["content"] == "Updated"
        assert client.post(f"/api/tasks/{task_id}/notes", json={"author_user_id": 1, "content": "No", "task_id": task_id}).status_code == 422
        deleted_task = client.delete(f"/api/tasks/{task_id}")
        assert deleted_task.status_code == 204 and deleted_task.content == b""
        assert client.get(f"/api/notes/{note_id}").status_code == 404

        standalone = client.post("/api/projects/1/tasks", json={"title": "Note delete"}).json()
        standalone_note = client.post(f"/api/tasks/{standalone['id']}/notes", json={"author_user_id": 1, "content": "Disposable"}).json()
        deleted_note = client.delete(f"/api/notes/{standalone_note['id']}")
        assert deleted_note.status_code == 204 and deleted_note.content == b""


def test_product_api_hides_storage_details_and_persists_across_lifespans(tmp_path) -> None:
    database = tmp_path / "product"
    with TestClient(create_app(data_dir=tmp_path / "demo", product_data_dir=database)) as client:
        created = client.post("/api/users", json={"name": "Persistent", "email": "persistent@strata.local"})
        assert created.status_code == 201
        payload = created.json()
        assert set(payload) == {"id", "name", "email", "account_state", "created_at", "deleted_at"}
        assert "password_hash" not in payload
        lowered = str(payload).lower()
        assert all(value not in lowered for value in ("rid", "tuple", "page", "slot", "index", "storage"))

    with TestClient(create_app(data_dir=tmp_path / "demo", product_data_dir=database)) as client:
        reopened = client.get("/api/users/2")
        assert reopened.status_code == 200
        assert reopened.json()["id"] == 2
        assert reopened.json()["name"] == "Persistent"
        assert reopened.json()["email"] == "persistent@strata.local"
        assert reopened.json()["account_state"] == "ACTIVE"
        assert reopened.json()["deleted_at"] is None
        assert isinstance(reopened.json()["created_at"], int)
