"""Safety and determinism checks for the persistent demo environment."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import secrets
import sys

import pytest

from strata_backend.product_bootstrap import initialize_product
from strata_backend.product_service import ProductService
from strata_engine import QueryResult, StrataEngine


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("strata_demo_script", ROOT / "scripts" / "demo.py")
assert SPEC is not None and SPEC.loader is not None
demo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = demo
SPEC.loader.exec_module(demo)


@pytest.fixture
def demo_root() -> Path:
    root = ROOT / ".verification" / f"demo-pytest-{secrets.token_hex(5)}"
    yield root
    if root.exists():
        paths = demo.demo_paths(root)
        if paths.marker.exists():
            demo.reset(paths)


def test_initialization_is_isolated_idempotent_and_realistic(demo_root: Path) -> None:
    paths = demo.demo_paths(demo_root)
    first = demo.initialize(paths)
    second = demo.initialize(paths)

    assert first["product"] == second["product"]
    assert first["sql"] == second["sql"]
    assert paths.product != paths.sql
    assert paths.product.is_relative_to(paths.root)
    assert paths.sql.is_relative_to(paths.root)

    product = StrataEngine(paths.product).open()
    try:
        initialize_product(product)
        service = ProductService(product)
        owner_session = service.authenticate_user(demo.OWNER["email"], demo.OWNER["password"])
        collaborator_session = service.authenticate_user(
            demo.COLLABORATOR["email"], demo.COLLABORATOR["password"],
        )
        assert owner_session is not None and collaborator_session is not None
        owner = service.get_user(owner_session.session.user_id)
        collaborator = service.get_user(collaborator_session.session.user_id)
        atlas = next(
            workspace for workspace in service.list_workspaces_for_user(owner.id, actor_user_id=owner.id)
            if workspace.name == demo.WORKSPACE_NAME
        )
        projects = service.list_projects(atlas.id, actor_user_id=owner.id)
        assert {project.name for project in projects} == set(demo.PROJECTS)
        tasks = [
            task for project in projects
            for task in service.list_tasks(project.id, actor_user_id=owner.id)
        ]
        assert len(tasks) == 7
        assert {task.status for task in tasks} == {"TODO", "IN_PROGRESS", "DONE"}
        assigned, _ = service.list_assigned_tasks(actor_user_id=collaborator.id)
        assert "Publish responsive landing page" in {item.task.title for item in assigned}
    finally:
        product.close()

    sql = StrataEngine(paths.sql).open()
    try:
        grouped = sql.execute(
            "SELECT status, COUNT(*) FROM demo_work_items GROUP BY status ORDER BY status"
        )
        joined = sql.execute(
            "SELECT demo_projects.name, demo_work_items.title FROM demo_projects "
            "INNER JOIN demo_work_items ON demo_projects.id = demo_work_items.project_id "
            "ORDER BY demo_work_items.id"
        )
        profile = sql.execute_profiled(
            "SELECT id FROM demo_work_items WHERE status = 'TODO' ORDER BY id"
        )
        assert isinstance(grouped, QueryResult) and len(grouped.rows) == 3
        assert isinstance(joined, QueryResult) and len(joined.rows) == 6
        assert profile.profile is not None
        assert type(profile.profile.metrics).__name__ == "IndexScanMetrics"
    finally:
        sql.close()


def test_reset_requires_exact_valid_marker(demo_root: Path) -> None:
    paths = demo.demo_paths(demo_root)
    demo.initialize(paths)
    paths.marker.write_text('{"kind":"forged"}\n', encoding="utf-8")

    with pytest.raises(demo.DemoError, match="marker"):
        demo.reset(paths)
    assert paths.root.exists()
    demo._atomic_json(paths.marker, demo._marker_value(paths))


def test_root_validation_rejects_paths_outside_demo_namespace(tmp_path: Path) -> None:
    with pytest.raises(demo.DemoError, match="inside"):
        demo.demo_paths(tmp_path / "demo")
    with pytest.raises(demo.DemoError, match="name"):
        demo.demo_paths(ROOT / ".verification" / "benchmark-results")


def test_stop_handles_absent_runtime_without_touching_storage(demo_root: Path) -> None:
    paths = demo.demo_paths(demo_root)
    demo.initialize(paths)
    result = demo.stop(paths)
    assert result["status"] == "passed"
    assert paths.product.exists() and paths.sql.exists()
