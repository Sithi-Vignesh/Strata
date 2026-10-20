"""Adversarial HTTP checks against real isolated product engines."""

import json

import pytest
from fastapi.testclient import TestClient

from strata_backend.main import create_app
from strata_backend.product_bootstrap import PRODUCT_SCHEMAS
from strata_backend.product_service import ProductService
from strata_engine import StrataEngine


@pytest.fixture
def team(tmp_path):
    app = create_app(data_dir=tmp_path / "sql", product_data_dir=tmp_path / "product")
    with TestClient(app, raise_server_exceptions=False) as client:
        users = []
        headers = []
        for name in ("Owner", "Member", "Outsider"):
            response = client.post("/api/auth/register", json={
                "name": name, "email": f"{name.lower()}@audit.local",
                "password": "audit correct horse battery",
            })
            assert response.status_code == 201, response.text
            users.append(response.json())
            headers.append({"cookie": f"strata_session={client.cookies.get('strata_session')}"})
        owner, member, outsider = users
        a, b, c = headers
        workspace = client.post("/api/workspaces", json={"name": "Audit"}, headers=a).json()
        wid = workspace["id"]
        assert client.post(f"/api/workspaces/{wid}/members", json={"email": member["email"]}, headers=a).status_code == 201
        project = client.post(f"/api/workspaces/{wid}/projects", json={"name": "Plan"}, headers=a).json()
        task = client.post(f"/api/projects/{project['id']}/tasks", json={"title": "Protected"}, headers=a).json()
        note = client.post(f"/api/tasks/{task['id']}/notes", json={"content": "Private note"}, headers=a).json()
        client.cookies.clear()
        yield client, app.state.product_service, users, headers, (wid, project["id"], task["id"], note["id"])
        persisted = snapshot(app.state.product_service)
    with StrataEngine(tmp_path / "product") as engine:
        assert snapshot(ProductService(engine)) == persisted


def snapshot(service):
    """Compare rows AND index entries, including session state, after denials."""
    with service._engine.operation():
        return {
            name: (
                tuple((rid, row.values) for rid, row in service._table(name).scan()),
                tuple((index.name, tuple(index.tree.scan_range())) for index in service._table(name).indexes),
            ) for name in PRODUCT_SCHEMAS
        }


def test_every_resource_denies_outsider_removed_member_and_missing_session_without_writes(team):
    client, service, users, headers, (w, p, t, n) = team
    owner, member, outsider = users
    a, b, c = headers
    routes = [
        ("GET", f"/users/{owner['id']}", None),
        ("PATCH", f"/users/{owner['id']}", {"name": "stolen"}),
        ("GET", f"/users/{owner['id']}/workspaces", None),
        ("GET", f"/workspaces/{w}", None),
        ("PATCH", f"/workspaces/{w}", {"name": "stolen"}),
        ("DELETE", f"/workspaces/{w}", None),
        ("GET", f"/workspaces/{w}/members", None),
        ("POST", f"/workspaces/{w}/members", {"email": outsider["email"]}),
        ("DELETE", f"/workspaces/{w}/members/{owner['id']}", None),
        ("POST", f"/workspaces/{w}/transfer-ownership", {"new_owner_user_id": outsider["id"]}),
        ("GET", f"/workspaces/{w}/projects", None),
        ("POST", f"/workspaces/{w}/projects", {"name": "stolen"}),
        ("GET", f"/projects/{p}", None),
        ("PATCH", f"/projects/{p}", {"name": "stolen"}),
        ("DELETE", f"/projects/{p}", None),
        ("GET", f"/projects/{p}/tasks", None),
        ("POST", f"/projects/{p}/tasks", {"title": "stolen"}),
        ("GET", f"/tasks/{t}", None),
        ("PATCH", f"/tasks/{t}", {"assignee_user_id": outsider["id"]}),
        ("DELETE", f"/tasks/{t}", None),
        ("GET", f"/tasks/{t}/notes", None),
        ("POST", f"/tasks/{t}/notes", {"content": "stolen"}),
        ("GET", f"/notes/{n}", None),
        ("PATCH", f"/notes/{n}", {"content": "stolen"}),
        ("DELETE", f"/notes/{n}", None),
    ]
    assert client.delete(f"/api/workspaces/{w}/members/{member['id']}", headers=a).status_code == 204
    before = snapshot(service)
    for actor, expected in ((c, 404), (b, 404), ({}, 401)):
        for method, url, body in routes:
            response = client.request(method, "/api" + url, headers=actor, json=body)
            assert response.status_code == expected, (method, url, response.text)
            assert snapshot(service) == before, (method, url)


def test_owner_member_personal_and_indirect_reference_boundaries(team):
    client, service, users, headers, (w, p, t, n) = team
    owner, member, outsider = users
    a, b, c = headers
    personal = service.list_workspaces_for_user(owner["id"])[0]
    before = snapshot(service)
    denials = [
        (b, "PATCH", f"/workspaces/{w}", {"name": "no"}, 403),
        (b, "DELETE", f"/workspaces/{w}", None, 403),
        (b, "POST", f"/workspaces/{w}/members", {"email": outsider["email"]}, 403),
        (b, "DELETE", f"/workspaces/{w}/members/{owner['id']}", None, 403),
        (b, "POST", f"/workspaces/{w}/transfer-ownership", {"new_owner_user_id": member["id"]}, 403),
        (b, "DELETE", f"/projects/{p}", None, 403),
        (b, "DELETE", f"/tasks/{t}", None, 403),
        (b, "PATCH", f"/notes/{n}", {"content": "no"}, 403),
        (b, "DELETE", f"/notes/{n}", None, 403),
        (a, "PATCH", f"/tasks/{t}", {"assignee_user_id": outsider["id"]}, 403),
        (a, "POST", f"/projects/{p}/tasks", {"title": "no", "assignee_user_id": outsider["id"]}, 403),
        (a, "POST", f"/workspaces/{w}/transfer-ownership", {"new_owner_user_id": outsider["id"]}, 409),
        (a, "POST", f"/workspaces/{personal.id}/members", {"email": member["email"]}, 403),
        (a, "PATCH", f"/workspaces/{personal.id}", {"name": "no"}, 403),
        (a, "DELETE", f"/workspaces/{personal.id}", None, 403),
        (c, "GET", f"/workspaces/{personal.id}", None, 404),
        (a, "POST", f"/projects/{p}/tasks", {"title": "no", "created_by_user_id": member["id"]}, 422),
        (a, "POST", f"/tasks/{t}/notes", {"content": "no", "author_user_id": member["id"]}, 422),
    ]
    for actor, method, url, body, expected in denials:
        response = client.request(method, "/api" + url, headers=actor, json=body)
        assert response.status_code == expected, (method, url, response.text)
        assert snapshot(service) == before


def test_untrusted_origin_cannot_submit_simple_post_with_session_cookie(team):
    client, service, users, headers, ids = team
    a = headers[0]
    before = snapshot(service)
    response = client.post("/api/auth/logout", headers={**a, "origin": "http://testserver:9999"})
    assert response.status_code == 403, response.text
    assert snapshot(service) == before
    # A browser can submit a simple POST without Content-Type using a Blob.
    # A different port on the same host is same-site, but is a different origin.
    response = client.post("/api/workspaces", content=b'{"name":"CSRF workspace"}', headers={
        **a, "origin": "http://testserver:9999", "sec-fetch-site": "same-site",
    })
    assert response.status_code == 403, response.text
    assert snapshot(service) == before
    for origin_headers in ({"origin": "null"}, {"origin": "http://testserver.evil.invalid"}, {"referer": "http://testserver:9999/attack"}, {"sec-fetch-site": "same-site"}, {"sec-fetch-site": "cross-site"}):
        response = client.post("/api/auth/logout", headers={**a, **origin_headers})
        assert response.status_code == 403
        assert snapshot(service) == before
    # Real JSON remains required by the framework for body-bearing routes.
    for content_type in ("text/plain", "application/x-www-form-urlencoded"):
        response = client.post("/api/workspaces", content=b'{"name":"bad type"}', headers={**a, "content-type": content_type, "origin": "http://testserver"})
        assert response.status_code == 422
        assert snapshot(service) == before
    for origin_headers in ({"origin": "http://testserver"}, {"origin": "http://localhost:5173"}, {"referer": "http://testserver/app"}, {}):
        response = client.patch(f"/api/tasks/{ids[2]}", json={"title": "Protected"}, headers={**a, **origin_headers})
        assert response.status_code == 200, response.text
        assert snapshot(service) == before
    assert client.post("/api/auth/logout", headers={**a, "origin": "http://testserver"}).status_code == 204
    assert client.get("/api/auth/me", headers=a).status_code == 401


@pytest.mark.parametrize("body", [{"title": "\ud800"}, {"assignee_user_id": True}, {"assignee_user_id": "3"}, {"assignee_user_id": 3.0}])
def test_malformed_unicode_and_wrong_id_types_are_clean_validation_errors(team, body):
    client, service, users, headers, (w, p, t, n) = team
    a = headers[0]
    before = snapshot(service)
    response = client.patch(f"/api/tasks/{t}", content=json.dumps(body), headers={**a, "content-type": "application/json"})
    assert response.status_code == 422, (body, response.text)
    assert snapshot(service) == before


def test_invalid_unicode_in_auth_sql_unknown_fields_and_invalid_json_is_safe(team):
    client, service, users, headers, ids = team
    before = snapshot(service)
    response = client.post("/api/auth/register", content=json.dumps({"email": "bad@audit.local", "password": "\ud800abcdefgh", "name": "Invalid"}), headers={"content-type": "application/json"})
    assert response.status_code == 422, response.text
    for url, body in (("/api/auth/login", {"email": "owner@audit.local", "password": "\ud800abcdefgh"}), ("/api/auth/register", {"\ud800": "bad", "password": "do-not-echo-this-password"}), ("/api/sql/profile", {"sql": "SELECT \ud800"})):
        response = client.post(url, content=json.dumps(body), headers={"content-type": "application/json"})
        assert response.status_code == 422, response.text
        assert "do-not-echo" not in response.text and "abcdefgh" not in response.text
    response = client.post("/api/workspaces", content=b'{"name":\xff}', headers={**headers[0], "content-type": "application/json"})
    assert response.status_code in (400, 422)
    assert snapshot(service) == before


def test_bounded_invalid_payloads_leave_server_and_records_healthy(team):
    client, service, users, headers, (w, p, t, n) = team
    a = headers[0]
    before = snapshot(service)
    for body in ({"title": ""}, {"title": " "}, {"title": "x" * 193}, {"title": None}, {"status": "BAD"}, {"priority": []}, {"project_id": p}, {"assignee_user_id": -1}, {"assignee_user_id": 0}):
        assert client.patch(f"/api/tasks/{t}", json=body, headers=a).status_code == 422
        assert snapshot(service) == before
    for task_id in (-1, 0, 2**100):
        response = client.get(f"/api/tasks/{task_id}", headers=a)
        assert response.status_code in (404, 422)
    for sql in ("SELECT", "SELECT * FROM", "SELECT '\u0000'", "DROP TABLE users", "SELECT * FROM ../../users"):
        response = client.post("/api/sql/profile", json={"sql": sql})
        assert response.status_code in (400, 422), response.text
    assert snapshot(service) == before
    assert client.get("/health").status_code == 200
    assert client.patch(f"/api/tasks/{t}", json={"title": "Valid café 日本語 🚀\nline"}, headers=a).status_code == 200
