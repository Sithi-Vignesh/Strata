"""HTTP request and response schemas for Strata product routes."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class _RequestModel(BaseModel):
    """Reject fields that do not belong to the public HTTP contract."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def text_must_be_encodable(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("Text must contain valid Unicode characters.") from None
        return value


class _ResponseModel(BaseModel):
    """Serialize immutable product-domain dataclasses at the HTTP boundary."""

    model_config = ConfigDict(from_attributes=True)


class RegisterAccount(_RequestModel):
    name: str
    email: str
    password: str


class LoginRequest(_RequestModel):
    email: str
    password: str


class UpdateUser(_RequestModel):
    name: str | None = None
    email: str | None = None


class CreateWorkspace(_RequestModel):
    name: str


class UpdateWorkspace(_RequestModel):
    name: str | None = None


class AddWorkspaceMember(_RequestModel):
    email: str


class TransferWorkspaceOwnership(_RequestModel):
    new_owner_user_id: StrictInt


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
    assignee_user_id: StrictInt | None = None
    due_date: str | None = None


class UpdateTask(_RequestModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_user_id: StrictInt | None = None
    due_date: str | None = None
    handoff_note: str | None = None


class NotificationReadState(_RequestModel):
    is_read: bool


class CreateNote(_RequestModel):
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
    name: str
    email: str
    account_state: str


class OwnershipTransferResponse(_ResponseModel):
    workspace_id: int
    owner_user_id: int
    previous_owner_user_id: int


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
    due_date: str | None = None


class AssignedTaskResponse(TaskResponse):
    project_name: str
    workspace_id: int
    workspace_name: str
    assignee_name: str | None = None


class AssignedTaskPage(_ResponseModel):
    items: list[AssignedTaskResponse]
    total: int
    limit: int
    offset: int


class DashboardResponse(_ResponseModel):
    scope: str
    workspace_id: int | None
    workspace_count: int
    project_count: int
    task_count: int
    assigned_to_me: int
    overdue_count: int
    upcoming_count: int
    completed_count: int
    status_counts: dict[str, int]
    priority_counts: dict[str, int]


class TaskActivityResponse(_ResponseModel):
    id: int
    task_id: int
    project_id: int
    workspace_id: int
    actor_user_id: int
    event_type: str
    details: dict[str, object] | None
    created_at: int


class TaskActivityPage(_ResponseModel):
    items: list[TaskActivityResponse]
    total: int
    limit: int
    offset: int


class NotificationResponse(_ResponseModel):
    id: int
    recipient_user_id: int
    event_type: str
    summary: str
    workspace_id: int | None
    project_id: int | None
    task_id: int | None
    created_at: int
    is_read: bool
    dismissed_at: int | None


class NotificationPage(_ResponseModel):
    items: list[NotificationResponse]
    total: int
    limit: int
    offset: int


class UnreadCountResponse(_ResponseModel):
    unread_count: int = Field(ge=0)


class NotificationUpdateCount(_ResponseModel):
    updated: int = Field(ge=0)


class NoteResponse(_ResponseModel):
    id: int
    task_id: int
    author_user_id: int
    content: str
    created_at: int
    updated_at: int
