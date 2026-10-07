"""Registration provisioning and compensation coverage for P1B-B."""

from pathlib import Path

import pytest

from strata_backend import product_service as product_service_module
from strata_backend.product_bootstrap import PRODUCT_SCHEMAS, bootstrap_product
from strata_backend.product_models import WorkspaceMember
from strata_backend.product_passwords import verify_password
from strata_backend.product_service import (
    ProductConflictError,
    ProductRegistrationCompensationError,
    ProductService,
    ProductValidationError,
)
from strata_engine import StrataEngine


def _rows(engine: StrataEngine) -> dict[str, tuple[tuple[object, ...], ...]]:
    return {
        name: tuple(row.values for _, row in engine.get_table(name).scan())
        for name in PRODUCT_SCHEMAS
    }


def _service(tmp_path: Path, *, token: str = "registered-token") -> tuple[StrataEngine, ProductService]:
    engine = StrataEngine(tmp_path / "strata").open()
    bootstrap_product(engine)
    return engine, ProductService(
        engine,
        clock=lambda: 1_800_000_000_000,
        token_factory=lambda: token,
    )


def test_register_account_provisions_personal_account_and_opaque_session(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        result = service.register_account("  Ada Lovelace  ", "  ADA@Example.Local  ", "correct horse battery staple")

        assert result.user.name == "Ada Lovelace"
        assert result.user.email == "ada@example.local"
        assert result.user.account_state == "ACTIVE"
        assert result.user.password_hash is not None
        assert result.user.password_hash != "correct horse battery staple"
        assert verify_password(result.user.password_hash, "correct horse battery staple")
        assert result.workspace.name == "My Workspace"
        assert result.workspace.kind == "PERSONAL"
        assert result.workspace.created_at == result.workspace.updated_at == result.user.created_at
        assert service.list_workspace_members(result.workspace.id) == (
            WorkspaceMember(result.workspace.id, result.user.id, "OWNER"),
        )
        assert result.personal_project.name == "Personal"
        assert result.personal_project.workspace_id == result.workspace.id
        assert result.personal_project.created_by_user_id == result.user.id
        assert result.personal_project.created_at == result.personal_project.updated_at == result.user.created_at
        assert result.session.user_id == result.user.id
        assert service.find_session_by_token(result.token) == result.session
        assert all(result.token not in row.values for _, row in engine.get_table("sessions").scan())
    finally:
        engine.close()


def test_register_account_rejects_duplicate_canonical_email_and_invalid_password(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        service.register_account("Ada", "Ada@Example.Local", "valid password")
        before = _rows(engine)
        with pytest.raises(ProductConflictError):
            service.register_account("Again", "  ADA@example.local  ", "valid password")
        assert _rows(engine) == before
        with pytest.raises(ProductValidationError):
            service.register_account("Invalid", "invalid@example.local", "short")
        assert _rows(engine) == before
    finally:
        engine.close()


@pytest.mark.parametrize("failed_table", ("users", "workspaces", "workspace_members", "projects", "sessions"))
def test_registration_compensates_each_primary_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_table: str) -> None:
    engine, service = _service(tmp_path)
    try:
        before = _rows(engine)
        monkeypatch.setattr(product_service_module, "hash_password", lambda _: "$argon2id$test")
        original_insert = service._registration_insert

        def fail_target(table_name: str, values: tuple[object, ...]):
            if table_name == failed_table:
                raise RuntimeError(f"injected {table_name} insert failure")
            return original_insert(table_name, values)

        monkeypatch.setattr(service, "_registration_insert", fail_target)
        with pytest.raises(RuntimeError, match=failed_table):
            service.register_account("Failure", "failure@example.local", "valid password")
        assert _rows(engine) == before
    finally:
        engine.close()


def test_registration_compensation_failure_remains_distinct_and_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, service = _service(tmp_path)
    try:
        monkeypatch.setattr(product_service_module, "hash_password", lambda _: "$argon2id$test")
        original_insert = service._registration_insert
        original_delete = service._registration_delete
        deletes: list[str] = []

        def fail_project_insert(table_name: str, values: tuple[object, ...]):
            if table_name == "projects":
                raise RuntimeError("injected project insert failure")
            return original_insert(table_name, values)

        def fail_workspace_delete(table_name: str, record_id):
            deletes.append(table_name)
            if table_name == "workspaces":
                raise RuntimeError("injected workspace delete failure")
            original_delete(table_name, record_id)

        monkeypatch.setattr(service, "_registration_insert", fail_project_insert)
        monkeypatch.setattr(service, "_registration_delete", fail_workspace_delete)
        with pytest.raises(ProductRegistrationCompensationError):
            service.register_account("Failure", "failure@example.local", "valid password")

        assert deletes == ["workspace_members", "workspaces", "users"]
        assert engine.get_table("users").count() == 1
        assert engine.get_table("workspace_members").count() == 1
        assert engine.get_table("projects").count() == 1
        assert engine.get_table("sessions").count() == 0
        assert engine.get_table("workspaces").count() == 2
    finally:
        engine.close()
