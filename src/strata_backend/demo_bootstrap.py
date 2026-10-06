"""Idempotent DBthon demo schema and data bootstrap."""

from strata_engine import Column, DataType, Schema, StrataEngine


TASKS_SCHEMA = Schema([
    Column("id", DataType.INTEGER),
    Column("title", DataType.VARCHAR, max_length=96),
    Column("status", DataType.VARCHAR, max_length=16),
    Column("priority", DataType.VARCHAR, max_length=16),
    Column("assignee", DataType.VARCHAR, nullable=True, max_length=32),
    Column("project", DataType.VARCHAR, max_length=32),
])

_STATUSES = ("TODO", "IN_PROGRESS", "REVIEW", "BLOCKED", "DONE")
_PRIORITIES = ("LOW", "MEDIUM", "HIGH", "URGENT")
_ASSIGNEES = ("Avery", "Blake", "Casey", "Devon", "Emery")
_PROJECTS = ("Strata Engine", "Mobile App", "Website", "Analytics", "Infrastructure")
_TASK_COUNT = 1000
_STATUS_INDEX_NAME = "tasks_status_idx"


class DemoBootstrapError(RuntimeError):
    """Raised when existing demo metadata conflicts with its fixed identity."""


def bootstrap_demo(engine: StrataEngine) -> None:
    """Create and seed the demo tasks table once, then ensure its status index."""
    if engine.has_table("tasks"):
        tasks = engine.get_table("tasks")
    else:
        tasks = engine.create_table("tasks", TASKS_SCHEMA)
        for task_id in range(1, _TASK_COUNT + 1):
            tasks.insert(_task_row(task_id))

    status_ordinal = tasks.schema.column_index("status")
    intended_index = next(
        (index for index in tasks.indexes if index.name.lower() == _STATUS_INDEX_NAME),
        None,
    )
    if intended_index is not None:
        if intended_index.column_ordinal != status_ordinal:
            raise DemoBootstrapError(
                f"Index '{_STATUS_INDEX_NAME}' must target tasks.status, "
                f"not column ordinal {intended_index.column_ordinal}."
            )
        return

    engine.create_index(_STATUS_INDEX_NAME, "tasks", "status")


def _task_row(task_id: int) -> tuple[object, ...]:
    """Return one deterministic, realistic task row."""
    offset = task_id - 1
    assignee = None if task_id % 11 == 0 else _ASSIGNEES[offset % len(_ASSIGNEES)]
    return (
        task_id,
        f"Implement storage task {task_id:03d}",
        _STATUSES[offset % len(_STATUSES)],
        _PRIORITIES[(offset * 3) % len(_PRIORITIES)],
        assignee,
        _PROJECTS[(offset * 2) % len(_PROJECTS)],
    )
