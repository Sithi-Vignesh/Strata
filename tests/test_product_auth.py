"""HTTP authentication-boundary coverage for P1B-C."""

from fastapi.testclient import TestClient
import pytest

from strata_backend import product_service as product_service_module
from strata_backend.main import create_app
from strata_backend.product_auth import SESSION_COOKIE_NAME
from strata_backend.product_sessions import session_token_digest
from strata_engine import Tuple


PASSWORD = "correct horse battery staple"


def _app(tmp_path):
    return create_app(data_dir=tmp_path / "demo", product_data_dir=tmp_path / "product")


def _register(client: TestClient, *, name: str = "Ada", email: str = "ada@example.local"):
    return client.post("/api/auth/register", json={"name": name, "email": email, "password": PASSWORD})


def _set_account_state(client: TestClient, user_id: int, state: str) -> None:
    table = client.app.state.product_service._engine.get_table("users")
    record_id, row = next((rid, row) for rid, row in table.scan() if row[0] == user_id)
    table.update(record_id, Tuple((row[0], row[1], row[2], row[3], state, row[5], row[6]), schema=row.schema))


def test_session_cookie_secure_configuration_is_strict_and_explicit_argument_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STRATA_SESSION_COOKIE_SECURE", raising=False)
    assert create_app(data_dir=tmp_path / "absent-demo", product_data_dir=tmp_path / "absent-product").state.session_cookie_secure is False

    for value in ("true", "TRUE", " true "):
        monkeypatch.setenv("STRATA_SESSION_COOKIE_SECURE", value)
        assert create_app(data_dir=tmp_path / f"{value}-demo", product_data_dir=tmp_path / f"{value}-product").state.session_cookie_secure is True
    for value in ("false", "FALSE", " false "):
        monkeypatch.setenv("STRATA_SESSION_COOKIE_SECURE", value)
        assert create_app(data_dir=tmp_path / f"{value}-demo", product_data_dir=tmp_path / f"{value}-product").state.session_cookie_secure is False
    for value in ("1", "yes", "on", "tru", ""):
        monkeypatch.setenv("STRATA_SESSION_COOKIE_SECURE", value)
        with pytest.raises(ValueError, match="STRATA_SESSION_COOKIE_SECURE"):
            create_app(data_dir=tmp_path / "invalid-demo", product_data_dir=tmp_path / "invalid-product")

    monkeypatch.setenv("STRATA_SESSION_COOKIE_SECURE", "invalid")
    assert create_app(
        data_dir=tmp_path / "explicit-true-demo",
        product_data_dir=tmp_path / "explicit-true-product",
        session_cookie_secure=True,
    ).state.session_cookie_secure is True
    assert create_app(
        data_dir=tmp_path / "explicit-false-demo",
        product_data_dir=tmp_path / "explicit-false-product",
        session_cookie_secure=False,
    ).state.session_cookie_secure is False


def test_registration_sets_one_securely_scoped_development_cookie(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = _register(client)

        assert response.status_code == 201
        assert set(response.json()) == {"id", "name", "email", "account_state", "created_at", "deleted_at"}
        assert all(secret not in response.text for secret in ("password_hash", "token_digest", "token"))
        cookie = response.headers["set-cookie"]
        lowered = cookie.lower()
        assert f"{SESSION_COOKIE_NAME}=" in cookie
        assert "httponly" in lowered
        assert "path=/" in lowered
        assert "samesite=lax" in lowered
        assert "max-age=2592000" in lowered
        assert "secure" not in lowered
        token = response.cookies.get(SESSION_COOKIE_NAME)
        assert token is not None
        service = client.app.state.product_service
        assert service.find_session_by_token(token) is not None
        assert client.app.state.product_service._engine.get_table("sessions").count() == 1


def test_login_is_canonical_sets_cookie_and_generically_rejects_invalid_accounts(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        registered = _register(client)
        client.cookies.clear()
        service = client.app.state.product_service
        sessions_before = service._engine.get_table("sessions").count()

        logged_in = client.post("/api/auth/login", json={"email": "  ADA@EXAMPLE.LOCAL  ", "password": PASSWORD})
        assert logged_in.status_code == 200
        assert logged_in.json()["id"] == registered.json()["id"]
        assert "httponly" in logged_in.headers["set-cookie"].lower()
        assert service._engine.get_table("sessions").count() == sessions_before + 1
        assert service.find_session_by_token(logged_in.cookies.get(SESSION_COOKIE_NAME)) is not None

        generic_failures = [
            client.post("/api/auth/login", json={"email": "ada@example.local", "password": "wrong password"}),
            client.post("/api/auth/login", json={"email": "missing@example.local", "password": PASSWORD}),
            client.post("/api/auth/login", json={"email": "sithi@strata.local", "password": PASSWORD}),
        ]
        pending = _register(client, name="Pending", email="pending@example.local")
        _set_account_state(client, pending.json()["id"], "PENDING_DELETION")
        generic_failures.append(client.post("/api/auth/login", json={"email": "pending@example.local", "password": PASSWORD}))
        deleted = _register(client, name="Deleted", email="deleted@example.local")
        _set_account_state(client, deleted.json()["id"], "DELETED")
        generic_failures.append(client.post("/api/auth/login", json={"email": "deleted@example.local", "password": PASSWORD}))
        assert all(response.status_code == 401 for response in generic_failures)
        assert {response.json()["detail"]["code"] for response in generic_failures} == {"INVALID_CREDENTIALS"}
        assert {response.json()["detail"]["message"] for response in generic_failures} == {"Invalid credentials."}


def test_password_verification_runs_outside_product_service_lock(tmp_path, monkeypatch) -> None:
    with TestClient(_app(tmp_path)) as client:
        registered = _register(client)
        client.cookies.clear()
        service = client.app.state.product_service
        observed_lock_states: list[bool] = []

        def verify_outside_lock(_: str, __: str) -> bool:
            observed_lock_states.append(service._lock._is_owned())
            return True

        monkeypatch.setattr(product_service_module, "verify_password", verify_outside_lock)
        response = client.post("/api/auth/login", json={"email": registered.json()["email"], "password": PASSWORD})
        assert response.status_code == 200
        assert observed_lock_states == [False]


def test_me_requires_live_active_session_and_logout_revokes_only_presented_session(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        missing = client.get("/api/auth/me")
        assert missing.status_code == 401
        assert missing.json()["detail"]["message"] == "Authentication required."
        assert client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: "not-a-valid-token"}).status_code == 401

        registered = _register(client)
        user_id = registered.json()["id"]
        service = client.app.state.product_service
        assert client.get("/api/auth/me").json()["id"] == user_id

        other = service.create_session(user_id)
        logout = client.post("/api/auth/logout")
        assert logout.status_code == 204 and logout.content == b""
        cleared = logout.headers["set-cookie"].lower()
        assert "max-age=0" in cleared and "path=/" in cleared and "samesite=lax" in cleared
        assert service.find_session_by_token(other.token) == other.session
        assert client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: registered.cookies.get(SESSION_COOKIE_NAME)}).status_code == 401

        assert client.post("/api/auth/logout").status_code == 204
        assert client.post("/api/auth/logout", cookies={SESSION_COOKIE_NAME: "unknown"}).status_code == 204


def test_expired_revoked_and_non_active_sessions_cannot_access_me(tmp_path) -> None:
    with TestClient(_app(tmp_path)) as client:
        service = client.app.state.product_service
        registered = service.register_account("Ada", "ada@example.local", PASSWORD)
        sessions = service._engine.get_table("sessions")
        sessions.insert((99, registered.user.id, session_token_digest("expired-token"), 1, 1))
        assert client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: "expired-token"}).status_code == 401

        revoked = service.create_session(registered.user.id)
        service.revoke_session(revoked.session.id)
        assert client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: revoked.token}).status_code == 401

        _set_account_state(client, registered.user.id, "DELETED")
        assert client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: registered.token}).status_code == 401
