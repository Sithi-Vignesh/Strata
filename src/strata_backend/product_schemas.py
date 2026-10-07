"""HTTP request and response schemas for Strata product routes."""

from pydantic import BaseModel, ConfigDict


class _RequestModel(BaseModel):
    """Reject fields that do not belong to the public HTTP contract."""

    model_config = ConfigDict(extra="forbid")


class _ResponseModel(BaseModel):
    """Serialize immutable product-domain dataclasses at the HTTP boundary."""

    model_config = ConfigDict(from_attributes=True)


class RegisterAccount(_RequestModel):
    name: str
    email: str
    password: str


class UpdateUser(_RequestModel):
    name: str | None = None
    email: str | None = None


class CreateWorkspace(_RequestModel):
    name: str
    owner_user_id: int


class UpdateWorkspace(_RequestModel):
    name: str | None = None


class CreateProject(_RequestModel):
    name: str
    description: str | None = None


class UpdateProject(_RequestModel):
    name: str | None = None
    description: str | None = None


class CreateTask(_RequestModel):
    title: str
    description: str | None = None
    status: str = "TODO"
    priority: str = "MEDIUM"
    assignee_user_id: int | None = None


class UpdateTask(_RequestModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_user_id: int | None = None


class CreateNote(_RequestModel):
    author_user_id: int
    content: str


class UpdateNote(_RequestModel):
    content: str | None = None


class UserResponse(_ResponseModel):
    id: int
    name: str
    email: str
    account_state: str
    created_at: int
    deleted_at: int | None


class WorkspaceResponse(_ResponseModel):
    id: int
    name: str
    kind: str
    created_at: int
    updated_at: int


class WorkspaceMemberResponse(_ResponseModel):
    workspace_id: int
    user_id: int
    role: str


class ProjectResponse(_ResponseModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    created_by_user_id: int
    created_at: int
    updated_at: int


class TaskResponse(_ResponseModel):
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


class NoteResponse(_ResponseModel):
    id: int
    task_id: int
    author_user_id: int
    content: str
    created_at: int
    updated_at: int
