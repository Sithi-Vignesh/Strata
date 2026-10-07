"""Application-facing immutable models for the Strata product domain."""

from dataclasses import dataclass


WORKSPACE_ROLES = frozenset({"OWNER", "MEMBER"})
WORKSPACE_KINDS = frozenset({"PERSONAL", "COLLABORATIVE"})
ACCOUNT_STATES = frozenset({"ACTIVE", "PENDING_DELETION", "DELETED"})
TASK_STATUSES = frozenset({"TODO", "IN_PROGRESS", "DONE"})
TASK_PRIORITIES = frozenset({"LOW", "MEDIUM", "HIGH"})


@dataclass(frozen=True, slots=True)
class User:
    id: int
    name: str
    email: str
    password_hash: str | None
    account_state: str
    created_at: int
    deleted_at: int | None


@dataclass(frozen=True, slots=True)
class Workspace:
    id: int
    name: str
    kind: str
    created_at: int
    updated_at: int


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
    created_by_user_id: int
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    project_id: int
    title: str
    description: str | None
    status: str
    priority: str
    assignee_user_id: int | None
    created_by_user_id: int
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class Note:
    id: int
    task_id: int
    author_user_id: int
    content: str
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class Session:
    """Persisted opaque-session metadata; never contains a raw token."""

    id: int
    user_id: int
    token_digest: str
    created_at: int
    expires_at: int


@dataclass(frozen=True, slots=True)
class CreatedSession:
    """A newly persisted session paired with its one-time raw bearer token."""

    session: Session
    token: str


@dataclass(frozen=True, slots=True)
class RegisteredAccount:
    """Internal result of successful account and personal-workspace provisioning."""

    user: User
    workspace: Workspace
    personal_project: Project
    session: Session
    token: str
