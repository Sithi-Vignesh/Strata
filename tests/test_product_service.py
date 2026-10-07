"""Focused B2A product create/read service coverage."""

from pathlib import Path

import pytest

from strata_backend.product_bootstrap import SEED_TIMESTAMP_MS, bootstrap_product, initialize_product
from strata_backend.product_models import Note, Task, User
from strata_backend.product_service import (
    ProductConflictError,
    ProductNotFoundError,
    ProductPermissionError,
    ProductService,
    ProductServiceError,
    ProductValidationError,
)
from strata_engine import RecordId, StrataEngine, Tuple


def _service(tmp_path: Path) -> tuple[StrataEngine, ProductService]:
    engine = StrataEngine(tmp_path / "strata").open()
    bootstrap_product(engine)
    return engine, ProductService(engine)


def test_seeded_read_workflow_returns_logical_models_in_id_order(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        assert service.get_user(1) == User(1, "Sithi", "sithi@strata.local", None, "ACTIVE", SEED_TIMESTAMP_MS, None)
        assert service.list_workspaces_for_user(1)[0].name == "Strata Team"
        assert service.list_workspace_members(1)[0].role == "OWNER"
        assert [project.id for project in service.list_projects(1)] == [1]
        assert [task.id for task in service.list_tasks(1)] == [1, 2, 3, 4, 5]
        assert [note.id for note in service.list_notes(1)] == [1]
        assert isinstance(service.get_task(1), Task)
        assert isinstance(service.get_note(1), Note)
        assert not isinstance(service.get_user(1), (RecordId, Tuple))
        with pytest.raises(ProductNotFoundError):
            service.get_project(999)
    finally:
        engine.close()


def test_create_user_and_workspace_enforces_uniqueness_and_owner_membership(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        user = service.create_user("Ada", "ada@strata.local")
        assert user.id == 2
        assert service.get_user(2) == user
        with pytest.raises(ProductConflictError):
            service.create_user("Ada Again", "ADA@STRATA.LOCAL")
        with pytest.raises(ProductValidationError):
            service.create_user(" ", "new@strata.local")
        with pytest.raises(ProductValidationError):
            service.create_user("Valid", " ")
        workspace = service.create_workspace("Ada Space", user.id)
        assert workspace.id == 2
        assert service.list_workspace_members(workspace.id)[0].user_id == user.id
        assert service.list_workspace_members(workspace.id)[0].role == "OWNER"
        with pytest.raises(ProductNotFoundError):
            service.create_workspace("Missing owner", 999)
        with pytest.raises(ProductValidationError):
            service.create_workspace(" ", user.id)
    finally:
        engine.close()


def test_project_task_and_note_enforce_relationship_and_domain_rules(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        other = service.create_user("Other", "other@strata.local")
        project = service.create_project(1, "New project")
        assert project.id == 2 and project.description is None
        assert service.get_project(project.id) == project
        with pytest.raises(ProductNotFoundError):
            service.create_project(999, "Missing workspace")
        with pytest.raises(ProductValidationError):
            service.create_project(1, " ")
        task = service.create_task(project.id, "Plan B2A", status="TODO", priority="HIGH", assignee_user_id=1)
        assert task.id == 6
        assert service.list_tasks(project.id) == (task,)
        default_task = service.create_task(project.id, "Defaults")
        assert default_task.status == "TODO" and default_task.priority == "MEDIUM"
        assert default_task.description is None and default_task.assignee_user_id is None
        with pytest.raises(ProductNotFoundError):
            service.create_task(999, "Missing project")
        with pytest.raises(ProductPermissionError):
            service.create_task(project.id, "Invalid assignment", assignee_user_id=other.id)
        with pytest.raises(ProductNotFoundError):
            service.create_task(project.id, "Missing assignee", assignee_user_id=999)
        with pytest.raises(ProductValidationError):
            service.create_task(project.id, "Bad status", status="BLOCKED")
        with pytest.raises(ProductValidationError):
            service.create_task(project.id, "Malformed status", status=[])  # type: ignore[arg-type]
        with pytest.raises(ProductValidationError):
            service.create_task(project.id, "Bad priority", priority="URGENT")
        with pytest.raises(ProductValidationError):
            service.create_task(project.id, " ")
        note = service.create_note(task.id, 1, "Start with direct Table APIs.")
        assert service.list_notes(task.id) == (note,)
        with pytest.raises(ProductNotFoundError):
            service.create_note(999, 1, "Missing task")
        with pytest.raises(ProductNotFoundError):
            service.create_note(task.id, 999, "Missing author")
        with pytest.raises(ProductPermissionError):
            service.create_note(task.id, other.id, "Not a member")
        with pytest.raises(ProductValidationError):
            service.create_note(task.id, 1, " ")
    finally:
        engine.close()


def test_created_rows_survive_reopen_and_bootstrap(tmp_path: Path) -> None:
    database = tmp_path / "strata"
    with StrataEngine(database) as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        created = service.create_user("Persistent", "persistent@strata.local")

    with StrataEngine(database) as engine:
        bootstrap_product(engine)
        assert ProductService(engine).get_user(created.id) == created


def test_service_rejects_closed_engine(tmp_path: Path) -> None:
    engine = StrataEngine(tmp_path / "strata")
    with pytest.raises(ProductServiceError):
        ProductService(engine)


def test_update_lifecycle_preserves_omitted_fields_and_nullable_values(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        user = service.update_user(1, name="Sithi Updated")
        assert user == User(1, "Sithi Updated", "sithi@strata.local", None, "ACTIVE", SEED_TIMESTAMP_MS, None)
        assert not isinstance(user, (RecordId, Tuple))
        assert service.update_user(1) == user
        with pytest.raises(ProductConflictError):
            duplicate = service.create_user("Ada", "ada@strata.local")
            service.update_user(1, email=duplicate.email.upper())
        with pytest.raises(ProductValidationError):
            service.update_user(1, email=" ")

        project = service.update_project(1, name="Strata Updated", description=None)
        assert project.workspace_id == 1 and project.description is None
        workspace = service.update_workspace(1, name="Renamed Team")
        assert workspace.id == 1 and workspace.name == "Renamed Team"
        with pytest.raises(ProductValidationError):
            service.update_workspace(1, name=" ")
        task = service.update_task(1, title="Updated task", description=None, status="TODO", priority="MEDIUM", assignee_user_id=None)
        assert task.id == 1 and task.project_id == 1 and task.description is None and task.assignee_user_id is None
        reassigned = service.update_task(1, assignee_user_id=1)
        assert reassigned.assignee_user_id == 1
        other = service.create_user("Other", "other@strata.local")
        with pytest.raises(ProductPermissionError):
            service.update_task(1, assignee_user_id=other.id)
        with pytest.raises(ProductNotFoundError):
            service.update_task(1, assignee_user_id=999)
        with pytest.raises(ProductValidationError):
            service.update_task(1, status="BLOCKED")
        with pytest.raises(ProductValidationError):
            service.update_task(1, priority="URGENT")
        with pytest.raises(ProductValidationError):
            service.update_task(1, title=" ")

        note = service.update_note(1, content="Updated note")
        assert note.task_id == 1 and note.author_user_id == 1 and note.content == "Updated note"
        with pytest.raises(ProductValidationError):
            service.update_note(1, content=" ")
        with pytest.raises(ProductNotFoundError):
            service.update_project(999, name="Missing")
    finally:
        engine.close()


def test_phase_1_metadata_is_attributed_immutable_and_timestamped(tmp_path: Path) -> None:
    engine = StrataEngine(tmp_path / "strata").open()
    try:
        bootstrap_product(engine)
        service = ProductService(engine, clock=lambda: 1_800_000_000_000)

        workspace = service.create_workspace("Timestamped workspace", 1)
        assert workspace.kind == "COLLABORATIVE"
        updated_workspace = service.update_workspace(workspace.id, name="Renamed timestamped workspace")
        assert updated_workspace.created_at == workspace.created_at
        assert updated_workspace.updated_at > workspace.updated_at

        project = service.create_project(workspace.id, "Attributed")
        assert project.created_by_user_id == 1
        assert project.created_at == project.updated_at == 1_800_000_000_000
        updated_project = service.update_project(project.id, name="Renamed attributed")
        assert updated_project.created_by_user_id == project.created_by_user_id
        assert updated_project.created_at == project.created_at
        assert updated_project.updated_at > project.updated_at

        task = service.create_task(updated_project.id, "Attributed task")
        assert task.created_by_user_id == project.created_by_user_id
        assert task.created_at == task.updated_at == 1_800_000_000_000

        updated_task = service.update_task(task.id, title="Updated attributed task")
        assert updated_task.created_by_user_id == task.created_by_user_id
        assert updated_task.created_at == task.created_at
        assert updated_task.updated_at > task.updated_at

        note = service.create_note(task.id, 1, "Timestamped")
        updated_note = service.update_note(note.id, content="Timestamped update")
        assert updated_note.author_user_id == note.author_user_id
        assert updated_note.created_at == note.created_at
        assert updated_note.updated_at > note.updated_at
    finally:
        engine.close()


def test_invalid_persisted_account_state_and_workspace_kind_are_rejected(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        engine.get_table("users").insert((99, "Invalid", "invalid@strata.local", None, "INVALID", 1, None))
        with pytest.raises(ProductValidationError, match="account_state"):
            service.get_user(99)

        engine.get_table("workspaces").insert((99, "Invalid", "INVALID", 1, 1))
        with pytest.raises(ProductValidationError, match="workspace kind"):
            service.get_workspace(99)
    finally:
        engine.close()


def test_delete_lifecycle_enforces_dependencies_and_cascades_notes(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    try:
        with pytest.raises(ProductConflictError):
            service.delete_project(1)
        with pytest.raises(ProductConflictError):
            service.delete_workspace(1)

        standalone = service.create_project(1, "Standalone")
        service.delete_project(standalone.id)
        with pytest.raises(ProductNotFoundError):
            service.get_project(standalone.id)

        task = service.create_task(1, "Disposable")
        first = service.create_note(task.id, 1, "First")
        second = service.create_note(task.id, 1, "Second")
        service.delete_note(first.id)
        with pytest.raises(ProductNotFoundError):
            service.get_note(first.id)
        service.delete_task(task.id)
        with pytest.raises(ProductNotFoundError):
            service.get_task(task.id)
        with pytest.raises(ProductNotFoundError):
            service.get_note(second.id)
        with pytest.raises(ProductNotFoundError):
            service.delete_task(999)
    finally:
        engine.close()


def test_workspace_delete_removes_memberships_and_b2b_changes_survive_reopen(tmp_path: Path) -> None:
    database = tmp_path / "strata"
    with StrataEngine(database) as engine:
        bootstrap_product(engine)
        service = ProductService(engine)
        workspace = service.create_workspace("Disposable", 1)
        service.delete_workspace(workspace.id)
        with pytest.raises(ProductNotFoundError):
            service.get_workspace(workspace.id)
        assert not any(row[0] == workspace.id for _, row in engine.get_table("workspace_members").scan())
        changed = service.update_task(1, status="IN_PROGRESS", assignee_user_id=None)

    with StrataEngine(database) as engine:
        bootstrap_product(engine)
        assert ProductService(engine).get_task(changed.id) == changed


def test_existing_service_rejects_operations_after_engine_closes(tmp_path: Path) -> None:
    engine, service = _service(tmp_path)
    engine.close()
    with pytest.raises(ProductServiceError):
        service.update_user(1, name="Closed")
