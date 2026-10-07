"""Application-facing immutable models for the Strata product domain."""

from dataclasses import dataclass


WORKSPACE_ROLES = frozenset({"OWNER", "MEMBER"})
TASK_STATUSES = frozenset({"TODO", "IN_PROGRESS", "DONE"})
TASK_PRIORITIES = frozenset({"LOW", "MEDIUM", "HIGH"})


@dataclass(frozen=True, slots=True)
class User:
    id: int
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class Workspace:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class WorkspaceMember:
    workspace_id: int
    user_id: int
    role: str


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    workspace_id: int
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    project_id: int
    title: str
    description: str | None
    status: str
    priority: str
    assignee_user_id: int | None


@dataclass(frozen=True, slots=True)
class Note:
    id: int
    task_id: int
    author_user_id: int
    content: str
