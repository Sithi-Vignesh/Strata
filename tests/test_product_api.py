"""HTTP boundary coverage for the authenticated product API."""

from fastapi.testclient import TestClient

from strata_backend.main import create_app


def _app(tmp_path):
    return create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")


def _detail(response):
    return response.json()["detail"]


def _register(client: TestClient, name: str, email: str) -> dict[str, object]:
    response = client.post("/api/auth/register", json={
        "name": name, "email": email, "password": "correct horse battery staple",
    })
    assert response.status_code == 201
    return response.json()


def _headers(client: TestClient) -> dict[str, str]:
    return {"cookie": f"strata_session={client.cookies.get('strata_session')}"}


def _personal_resources(client: TestClient, user_id: int, headers: dict[str, str]) -> tuple[int, int]:
    workspace_id = client.get(f"/api/users/{user_id}/workspaces", headers=headers).json()[0]["id"]
    project_id = client.get(f"/api/workspaces/{workspace_id}/projects", headers=headers).json()[0]["id"]
    return workspace_id, project_id


def test_product_storage_is_created_only_during_lifespan(tmp_path) -> None:
    product_database = tmp_path / "product"
    app = create_app(data_dir=tmp_path / "demo", product_data_dir=product_database)
    assert not product_database.exists()
    with TestClient(app) as client:
        assert product_database.is_dir()
        assert client.get("/api/users/1").status_code == 401
        user = _register(client, "Lifecycle", "lifecycle@strata.local")
        assert client.get(f"/api/users/{user['id']}").status_code == 200


def test_product_api_registration_workspace_and_health_contract(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "service": "strata_backend", "engine": {"name": "StrataEngine", "status": "open", "initialized": True}}
        created = _register(client, "Ada", "ada@strata.local")
        user_id = created["id"]
        assert created == {"id": user_id, "name": "Ada", "email": "ada@strata.local", "account_state": "ACTIVE", "created_at": created["created_at"], "deleted_at": None}
        assert client.get(f"/api/users/{user_id}").json() == created
        assert client.patch(f"/api/users/{user_id}", json={"name": "Ada Lovelace"}).json()["name"] == "Ada Lovelace"
        duplicate = client.post("/api/auth/register", json={"name": "Again", "email": "ADA@STRATA.LOCAL", "password": "correct horse battery staple"})
        assert duplicate.status_code == 409 and _detail(duplicate)["code"] == "PRODUCT_CONFLICT"
        missing = client.get("/api/users/999")
        assert missing.status_code == 404 and _detail(missing)["code"] == "PRODUCT_NOT_FOUND"
        assert client.post("/api/auth/register", json={"name": "Extra", "email": "extra@strata.local", "password": "correct horse battery staple", "role": "X"}).status_code == 422
        assert client.post("/api/users", json={"name": "No", "email": "no@strata.local"}).status_code == 404
        workspace = client.post("/api/workspaces", json={"name": "Ada Space"})
        assert workspace.status_code == 201
        workspace_id = workspace.json()["id"]
        assert client.get(f"/api/workspaces/{workspace_id}").json() == workspace.json()
        assert workspace.json() in client.get(f"/api/users/{user_id}/workspaces").json()
        assert client.patch(f"/api/workspaces/{workspace_id}", json={"name": "Ada Workspace"}).status_code == 200
        assert client.get(f"/api/workspaces/{workspace_id}/members").json() == [{
            "workspace_id": workspace_id, "user_id": user_id, "role": "OWNER",
            "name": "Ada Lovelace", "email": "ada@strata.local", "account_state": "ACTIVE",
        }]
        deleted = client.delete(f"/api/workspaces/{workspace_id}")
        assert deleted.status_code == 204 and deleted.content == b""
        cors = client.options(f"/api/users/{user_id}", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PATCH"})
        assert cors.status_code == 200 and "PATCH" in cors.headers["access-control-allow-methods"]


def test_project_routes_patch_null_and_dependency_conflict(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = _register(client, "Projects", "projects@strata.local")
        headers = _headers(client)
        workspace_id, _ = _personal_resources(client, user["id"], headers)
        created = client.post(f"/api/workspaces/{workspace_id}/projects", json={"name": "HTTP project", "description": "Initial"}, headers=headers)
        assert created.status_code == 201
        project_id = created.json()["id"]
        assert created.json()["created_by_user_id"] == user["id"]
        assert client.get(f"/api/workspaces/{workspace_id}/projects", headers=headers).json()[-1]["id"] == project_id
        assert client.get(f"/api/projects/{project_id}", headers=headers).json() == created.json()
        assert client.patch(f"/api/projects/{project_id}", json={"name": "Renamed"}, headers=headers).json()["description"] == "Initial"
        cleared = client.patch(f"/api/projects/{project_id}", json={"description": None}, headers=headers)
        assert cleared.status_code == 200 and cleared.json()["description"] is None
        assert client.post(f"/api/workspaces/{workspace_id}/projects", json={"name": "No", "workspace_id": workspace_id}, headers=headers).status_code == 422
        deleted = client.delete(f"/api/projects/{project_id}", headers=headers)
        assert deleted.status_code == 204 and deleted.content == b""
        dependency_workspace = client.post("/api/workspaces", json={"name": "Dependency Space"}, headers=headers).json()
        dependency_project = client.post(f"/api/workspaces/{dependency_workspace['id']}/projects", json={"name": "Dependency Project"}, headers=headers).json()
        assert client.post(f"/api/projects/{dependency_project['id']}/tasks", json={"title": "Dependency"}, headers=headers).status_code == 201
        blocked = client.delete(f"/api/projects/{dependency_project['id']}", headers=headers)
        assert blocked.status_code == 409 and _detail(blocked)["code"] == "PRODUCT_CONFLICT"
        workspace_blocked = client.delete(f"/api/workspaces/{dependency_workspace['id']}", headers=headers)
        assert workspace_blocked.status_code == 409 and _detail(workspace_blocked)["code"] == "PRODUCT_CONFLICT"


def test_task_note_routes_patch_semantics_permissions_and_cascade(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = _register(client, "Tasks", "tasks@strata.local")
        headers = _headers(client)
        _, project_id = _personal_resources(client, user["id"], headers)
        task = client.post(f"/api/projects/{project_id}/tasks", json={"title": "HTTP task", "description": "Initial", "assignee_user_id": user["id"]}, headers=headers)
        assert task.status_code == 201
        task_id = task.json()["id"]
        assert task.json()["created_by_user_id"] == user["id"]
        assert client.get(f"/api/projects/{project_id}/tasks", headers=headers).json()[-1]["id"] == task_id
        assert client.get(f"/api/tasks/{task_id}", headers=headers).json()["title"] == "HTTP task"
        assert client.patch(f"/api/tasks/{task_id}", json={}, headers=headers).json()["description"] == "Initial"
        assert client.patch(f"/api/tasks/{task_id}", json={"description": None}, headers=headers).json()["description"] is None
        assert client.patch(f"/api/tasks/{task_id}", json={"assignee_user_id": None}, headers=headers).json()["assignee_user_id"] is None
        assert client.patch(f"/api/tasks/{task_id}", json={"status": "IN_PROGRESS"}, headers=headers).json()["status"] == "IN_PROGRESS"
        assert client.patch(f"/api/tasks/{task_id}", json={"created_by_user_id": user["id"]}, headers=headers).status_code == 422
        assert client.patch(f"/api/tasks/{task_id}", json={"created_at": 1}, headers=headers).status_code == 422
        invalid_status = client.patch(f"/api/tasks/{task_id}", json={"status": "BLOCKED"}, headers=headers)
        assert invalid_status.status_code == 422 and _detail(invalid_status)["code"] == "PRODUCT_VALIDATION_ERROR"
        invalid_priority = client.patch(f"/api/tasks/{task_id}", json={"priority": "URGENT"}, headers=headers)
        assert invalid_priority.status_code == 422 and _detail(invalid_priority)["code"] == "PRODUCT_VALIDATION_ERROR"
        assert client.patch(f"/api/tasks/{task_id}", json={"title": None}, headers=headers).status_code == 422
        assert client.post(f"/api/projects/{project_id}/tasks", json={"title": "No", "project_id": project_id}, headers=headers).status_code == 422
        other = _register(client, "Other", "other@strata.local")
        denied = client.patch(f"/api/tasks/{task_id}", json={"assignee_user_id": other["id"]}, headers=headers)
        assert denied.status_code == 403 and _detail(denied)["code"] == "PRODUCT_PERMISSION_DENIED"
        note = client.post(f"/api/tasks/{task_id}/notes", json={"content": "HTTP note"}, headers=headers)
        assert note.status_code == 201
        note_id = note.json()["id"]
        assert note.json()["author_user_id"] == user["id"]
        assert client.get(f"/api/tasks/{task_id}/notes", headers=headers).json()[-1]["id"] == note_id
        assert client.get(f"/api/notes/{note_id}", headers=headers).json()["content"] == "HTTP note"
        assert client.patch(f"/api/notes/{note_id}", json={"content": "Updated"}, headers=headers).json()["content"] == "Updated"
        assert client.post(f"/api/tasks/{task_id}/notes", json={"content": "No", "task_id": task_id}, headers=headers).status_code == 422
        deleted_task = client.delete(f"/api/tasks/{task_id}", headers=headers)
        assert deleted_task.status_code == 204 and deleted_task.content == b""
        assert client.get(f"/api/notes/{note_id}", headers=headers).status_code == 404
        standalone = client.post(f"/api/projects/{project_id}/tasks", json={"title": "Note delete"}, headers=headers).json()
        standalone_note = client.post(f"/api/tasks/{standalone['id']}/notes", json={"content": "Disposable"}, headers=headers).json()
        deleted_note = client.delete(f"/api/notes/{standalone_note['id']}", headers=headers)
        assert deleted_note.status_code == 204 and deleted_note.content == b""


def test_product_api_hides_storage_details_and_persists_across_lifespans(tmp_path) -> None:
    database = tmp_path / "product"
    password = "correct horse battery staple"
    with TestClient(create_app(data_dir=tmp_path / "demo", product_data_dir=database)) as client:
        created = client.post("/api/auth/register", json={"name": "Persistent", "email": "persistent@strata.local", "password": password})
        assert created.status_code == 201
        payload = created.json()
        user_id = payload["id"]
        assert set(payload) == {"id", "name", "email", "account_state", "created_at", "deleted_at"}
        assert "password_hash" not in payload and "token_digest" not in payload and "token" not in payload
        assert all(value not in str(payload).lower() for value in ("rid", "tuple", "page", "slot", "index", "storage"))
    with TestClient(create_app(data_dir=tmp_path / "demo", product_data_dir=database)) as client:
        login = client.post("/api/auth/login", json={"email": "persistent@strata.local", "password": password})
        assert login.status_code == 200
        reopened = client.get(f"/api/users/{user_id}")
        assert reopened.status_code == 200
        assert reopened.json()["id"] == user_id
        assert reopened.json()["name"] == "Persistent"
        assert reopened.json()["email"] == "persistent@strata.local"
        assert reopened.json()["account_state"] == "ACTIVE"
        assert reopened.json()["deleted_at"] is None
        assert isinstance(reopened.json()["created_at"], int)
