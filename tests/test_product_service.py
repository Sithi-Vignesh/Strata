"""Focused B2A product create/read service coverage."""

from pathlib import Path

import pytest

from strata_backend.product_bootstrap import bootstrap_product, initialize_product
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
        assert service.get_user(1) == User(1, "Sithi", "sithi@strata.local")
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
