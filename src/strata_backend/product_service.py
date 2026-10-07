"""Create/read/update/delete product workflow over Strata's Table APIs."""

from threading import RLock
from typing import Callable, TypeVar

from strata_engine import StrataEngine, Tuple
from strata_engine.catalog import Table
from strata_engine.storage import RecordId

from strata_backend.product_models import (
    ACCOUNT_STATES,
    TASK_PRIORITIES,
    TASK_STATUSES,
    WORKSPACE_KINDS,
    WORKSPACE_ROLES,
    Note,
    Project,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from strata_backend.product_time import utc_epoch_milliseconds


class ProductServiceError(RuntimeError):
    """Base error for application-level product operations."""


class ProductNotFoundError(ProductServiceError):
    """Raised when a requested logical product entity does not exist."""


class ProductConflictError(ProductServiceError):
    """Raised when an application-level uniqueness invariant is violated."""


class ProductValidationError(ProductServiceError):
    """Raised when product input violates a supported domain rule."""


class ProductPermissionError(ProductServiceError):
    """Raised when required workspace-membership context is absent.

    This represents a domain rule only; authentication and full authorization are
    intentionally outside the current product-service scope.
    """


ModelT = TypeVar("ModelT")


class _Unset:
    __slots__ = ()


_UNSET = _Unset()


class ProductService:
    """Application integrity boundary for Strata's initial product lifecycle.

    Every public operation is serialized by this instance's process-local lock.
    That prevents duplicate ``MAX + 1``-style allocation within this service
    instance only. It is not a database transaction, rollback mechanism, ACID
    guarantee, database lock, 2PL, MVCC, or cross-process synchronization.
    """

    def __init__(self, engine: StrataEngine, *, clock: Callable[[], int] = utc_epoch_milliseconds) -> None:
        if not isinstance(engine, StrataEngine):
            raise TypeError(f"Expected StrataEngine, got {type(engine).__name__}.")
        if not engine.is_open:
            raise ProductServiceError("ProductService requires an open StrataEngine.")
        if not callable(clock):
            raise TypeError("clock must be callable.")
        self._engine = engine
        self._lock = RLock()
        self._clock = clock

    def get_user(self, user_id: int) -> User:
        with self._lock:
            return self._user_for_id(user_id)

    def get_workspace(self, workspace_id: int) -> Workspace:
        with self._lock:
            return self._workspace_for_id(workspace_id)

    def list_workspaces_for_user(self, user_id: int) -> tuple[Workspace, ...]:
        with self._lock:
            self._user_for_id(user_id)
            workspace_ids = {member.workspace_id for member in self._members_for_user(user_id)}
            return tuple(sorted((self._workspace_for_id(item) for item in workspace_ids), key=lambda item: item.id))

    def list_workspace_members(self, workspace_id: int) -> tuple[WorkspaceMember, ...]:
        with self._lock:
            self._workspace_for_id(workspace_id)
            return tuple(sorted(self._members_for_workspace(workspace_id), key=lambda item: (item.user_id, item.role)))

    def get_project(self, project_id: int) -> Project:
        with self._lock:
            return self._project_for_id(project_id)

    def list_projects(self, workspace_id: int) -> tuple[Project, ...]:
        with self._lock:
            self._workspace_for_id(workspace_id)
            return tuple(sorted((self._validated_project(row) for _, row in self._indexed_records("projects", "workspace_id", workspace_id)), key=lambda item: item.id))

    def get_task(self, task_id: int) -> Task:
        with self._lock:
            return self._task_for_id(task_id)

    def list_tasks(self, project_id: int) -> tuple[Task, ...]:
        with self._lock:
            self._project_for_id(project_id)
            return tuple(sorted((self._validated_task(row) for _, row in self._indexed_records("tasks", "project_id", project_id)), key=lambda item: item.id))

    def get_note(self, note_id: int) -> Note:
        with self._lock:
            return self._note_for_id(note_id)

    def list_notes(self, task_id: int) -> tuple[Note, ...]:
        with self._lock:
            self._task_for_id(task_id)
            return tuple(sorted(self._indexed_models("notes", "task_id", task_id, self._note), key=lambda item: item.id))

    def create_user(self, name: str, email: str) -> User:
        with self._lock:
            name = self._required_text("name", name)
            email = self._required_text("email", email)
            if any(user.email.casefold() == email.casefold() for user in self._all_models("users", self._user)):
                raise ProductConflictError(f"A user with email '{email}' already exists.")
            user = User(self._next_id("users"), name, email, None, "ACTIVE", self._now(), None)
            self._table("users").insert((
                user.id, user.name, user.email, user.password_hash,
                user.account_state, user.created_at, user.deleted_at,
            ))
            return user

    def create_workspace(self, name: str, owner_user_id: int) -> Workspace:
        with self._lock:
            name = self._required_text("name", name)
            self._user_for_id(owner_user_id)
            now = self._now()
            workspace = Workspace(self._next_id("workspaces"), name, "COLLABORATIVE", now, now)
            # This pair of inserts is process-serialized but is not rollback-safe.
            self._table("workspaces").insert((
                workspace.id, workspace.name, workspace.kind,
                workspace.created_at, workspace.updated_at,
            ))
            self._create_membership(workspace.id, owner_user_id, "OWNER")
            return workspace

    def create_project(self, workspace_id: int, name: str, description: str | None = None) -> Project:
        with self._lock:
            self._workspace_for_id(workspace_id)
            name = self._required_text("name", name)
            description = self._optional_text("description", description)
            # P1A compatibility only: unauthenticated project creation is attributed
            # to the workspace's sole OWNER until authenticated actor propagation lands.
            creator_id = self._workspace_owner_id(workspace_id)
            now = self._now()
            project = Project(self._next_id("projects"), workspace_id, name, description, creator_id, now, now)
            self._table("projects").insert((
                project.id, project.workspace_id, project.name, project.description,
                project.created_by_user_id, project.created_at, project.updated_at,
            ))
            return project

    def create_task(
        self,
        project_id: int,
        title: str,
        description: str | None = None,
        status: str = "TODO",
        priority: str = "MEDIUM",
        assignee_user_id: int | None = None,
    ) -> Task:
        with self._lock:
            project = self._project_for_id(project_id)
            title = self._required_text("title", title)
            description = self._optional_text("description", description)
            self._allowed("status", status, TASK_STATUSES)
            self._allowed("priority", priority, TASK_PRIORITIES)
            if assignee_user_id is not None:
                self._user_for_id(assignee_user_id)
                self._require_membership(project.workspace_id, assignee_user_id, "assignee")
            self._validate_project_creator(project)
            now = self._now()
            task = Task(
                self._next_id("tasks"), project_id, title, description, status, priority,
                assignee_user_id, project.created_by_user_id, now, now,
            )
            self._table("tasks").insert((
                task.id, task.project_id, task.title, task.description,
                task.status, task.priority, task.assignee_user_id, task.created_by_user_id,
                task.created_at, task.updated_at,
            ))
            return task

    def create_note(self, task_id: int, author_user_id: int, content: str) -> Note:
        with self._lock:
            task = self._task_for_id(task_id)
            self._user_for_id(author_user_id)
            project = self._project_for_id(task.project_id)
            self._require_membership(project.workspace_id, author_user_id, "note author")
            now = self._now()
            note = Note(self._next_id("notes"), task_id, author_user_id, self._required_text("content", content), now, now)
            self._table("notes").insert((
                note.id, note.task_id, note.author_user_id, note.content,
                note.created_at, note.updated_at,
            ))
            return note

    def update_user(self, user_id: int, *, name: str | _Unset = _UNSET, email: str | _Unset = _UNSET) -> User:
        with self._lock:
            record_id, row = self._record_or_not_found("users", user_id)
            current = self._user(row)
            next_name = current.name if name is _UNSET else self._required_text("name", name)
            next_email = current.email if email is _UNSET else self._required_text("email", email)
            if email is not _UNSET and any(
                user.id != current.id and user.email.casefold() == next_email.casefold()
                for user in self._all_models("users", self._user)
            ):
                raise ProductConflictError(f"A user with email '{next_email}' already exists.")
            updated = User(
                current.id, next_name, next_email, current.password_hash,
                current.account_state, current.created_at, current.deleted_at,
            )
            if updated != current:
                self._table("users").update(record_id, Tuple((
                    updated.id, updated.name, updated.email, updated.password_hash,
                    updated.account_state, updated.created_at, updated.deleted_at,
                ), schema=row.schema))
            return updated

    def update_workspace(self, workspace_id: int, *, name: str | _Unset = _UNSET) -> Workspace:
        with self._lock:
            record_id, row = self._record_or_not_found("workspaces", workspace_id)
            current = self._workspace(row)
            next_name = current.name if name is _UNSET else self._required_text("name", name)
            updated = Workspace(
                current.id, next_name, current.kind, current.created_at,
                current.updated_at if next_name == current.name else self._later_than(current.updated_at),
            )
            if updated != current:
                self._table("workspaces").update(record_id, Tuple((
                    updated.id, updated.name, updated.kind, updated.created_at, updated.updated_at,
                ), schema=row.schema))
            return updated

    def update_project(
        self, project_id: int, *, name: str | _Unset = _UNSET, description: str | None | _Unset = _UNSET,
    ) -> Project:
        with self._lock:
            record_id, row = self._record_or_not_found("projects", project_id)
            current = self._validated_project(row)
            next_name = current.name if name is _UNSET else self._required_text("name", name)
            next_description = current.description if description is _UNSET else self._optional_text("description", description)
            changed = next_name != current.name or next_description != current.description
            updated = Project(
                current.id, current.workspace_id, next_name, next_description,
                current.created_by_user_id, current.created_at,
                current.updated_at if not changed else self._later_than(current.updated_at),
            )
            if updated != current:
                self._table("projects").update(record_id, Tuple((
                    updated.id, updated.workspace_id, updated.name, updated.description,
                    updated.created_by_user_id, updated.created_at, updated.updated_at,
                ), schema=row.schema))
            return updated

    def update_task(
        self,
        task_id: int,
        *,
        title: str | _Unset = _UNSET,
        description: str | None | _Unset = _UNSET,
        status: str | _Unset = _UNSET,
        priority: str | _Unset = _UNSET,
        assignee_user_id: int | None | _Unset = _UNSET,
    ) -> Task:
        with self._lock:
            record_id, row = self._record_or_not_found("tasks", task_id)
            current = self._validated_task(row)
            next_title = current.title if title is _UNSET else self._required_text("title", title)
            next_description = current.description if description is _UNSET else self._optional_text("description", description)
            next_status = current.status if status is _UNSET else self._allowed("status", status, TASK_STATUSES)
            next_priority = current.priority if priority is _UNSET else self._allowed("priority", priority, TASK_PRIORITIES)
            next_assignee = current.assignee_user_id if assignee_user_id is _UNSET else assignee_user_id
            if next_assignee is not None:
                self._user_for_id(next_assignee)
                project = self._project_for_id(current.project_id)
                self._require_membership(project.workspace_id, next_assignee, "assignee")
            changed = (
                next_title != current.title or next_description != current.description
                or next_status != current.status or next_priority != current.priority
                or next_assignee != current.assignee_user_id
            )
            updated = Task(
                current.id, current.project_id, next_title, next_description, next_status,
                next_priority, next_assignee, current.created_by_user_id, current.created_at,
                current.updated_at if not changed else self._later_than(current.updated_at),
            )
            if updated != current:
                self._table("tasks").update(record_id, Tuple((
                    updated.id, updated.project_id, updated.title, updated.description,
                    updated.status, updated.priority, updated.assignee_user_id,
                    updated.created_by_user_id, updated.created_at, updated.updated_at,
                ), schema=row.schema))
            return updated

    def update_note(self, note_id: int, *, content: str | _Unset = _UNSET) -> Note:
        with self._lock:
            record_id, row = self._record_or_not_found("notes", note_id)
            current = self._note(row)
            next_content = current.content if content is _UNSET else self._required_text("content", content)
            updated = Note(
                current.id, current.task_id, current.author_user_id, next_content,
                current.created_at,
                current.updated_at if next_content == current.content else self._later_than(current.updated_at),
            )
            if updated != current:
                self._table("notes").update(record_id, Tuple((
                    updated.id, updated.task_id, updated.author_user_id, updated.content,
                    updated.created_at, updated.updated_at,
                ), schema=row.schema))
            return updated

    def delete_note(self, note_id: int) -> None:
        with self._lock:
            record_id, _ = self._record_or_not_found("notes", note_id)
            self._table("notes").delete(record_id)

    def delete_task(self, task_id: int) -> None:
        with self._lock:
            record_id, _ = self._record_or_not_found("tasks", task_id)
            note_records = self._indexed_records("notes", "task_id", task_id)
            for note_record_id, _ in note_records:
                self._table("notes").delete(note_record_id)
            self._table("tasks").delete(record_id)

    def delete_project(self, project_id: int) -> None:
        with self._lock:
            record_id, _ = self._record_or_not_found("projects", project_id)
            if self._indexed_records("tasks", "project_id", project_id):
                raise ProductConflictError("Cannot delete a project that still has tasks.")
            self._table("projects").delete(record_id)

    def delete_workspace(self, workspace_id: int) -> None:
        with self._lock:
            record_id, _ = self._record_or_not_found("workspaces", workspace_id)
            if self._indexed_records("projects", "workspace_id", workspace_id):
                raise ProductConflictError("Cannot delete a workspace that still has projects.")
            member_records = self._indexed_records("workspace_members", "workspace_id", workspace_id)
            for member_record_id, _ in member_records:
                self._table("workspace_members").delete(member_record_id)
            self._table("workspaces").delete(record_id)

    def _table(self, name: str) -> Table:
        if not self._engine.is_open:
            raise ProductServiceError("ProductService cannot use a closed StrataEngine.")
        return self._engine.get_table(name)

    def _next_id(self, table_name: str) -> int:
        values = [row[0] for _, row in self._table(table_name).scan()]
        return 1 if not values else max(values) + 1

    def _find(self, table_name: str, logical_id: int) -> tuple[RecordId, Tuple] | None:
        self._logical_id(logical_id)
        return next(((rid, row) for rid, row in self._table(table_name).scan() if row[0] == logical_id), None)

    def _record_or_not_found(self, table_name: str, logical_id: int) -> tuple[RecordId, Tuple]:
        found = self._find(table_name, logical_id)
        if found is None:
            raise ProductNotFoundError(f"{table_name.rstrip('s').replace('_', ' ').title()} {logical_id} does not exist.")
        return found

    def _required(self, table_name: str, logical_id: int, mapper: Callable[[Tuple], ModelT]) -> ModelT:
        found = self._record_or_not_found(table_name, logical_id)
        return mapper(found[1])

    def _user_for_id(self, user_id: int) -> User:
        return self._required("users", user_id, self._user)

    def _workspace_for_id(self, workspace_id: int) -> Workspace:
        return self._required("workspaces", workspace_id, self._workspace)

    def _project_for_id(self, project_id: int) -> Project:
        record_id, row = self._record_or_not_found("projects", project_id)
        del record_id
        return self._validated_project(row)

    def _task_for_id(self, task_id: int) -> Task:
        record_id, row = self._record_or_not_found("tasks", task_id)
        del record_id
        return self._validated_task(row)

    def _note_for_id(self, note_id: int) -> Note:
        return self._required("notes", note_id, self._note)

    def _all_models(self, table_name: str, mapper: Callable[[Tuple], ModelT]) -> tuple[ModelT, ...]:
        return tuple(mapper(row) for _, row in self._table(table_name).scan())

    def _indexed_models(self, table_name: str, column_name: str, value: object, mapper: Callable[[Tuple], ModelT]) -> tuple[ModelT, ...]:
        return tuple(mapper(row) for _, row in self._indexed_records(table_name, column_name, value))

    def _indexed_records(self, table_name: str, column_name: str, value: object) -> tuple[tuple[RecordId, Tuple], ...]:
        table = self._table(table_name)
        index = table.index_for_column(column_name)
        if index is None:
            records = tuple((record_id, row) for record_id, row in table.scan() if row[table.schema.column_index(column_name)] == value)
        else:
            records = tuple((record_id, table.get(record_id)) for record_id in index.tree.search(value))
        return tuple(sorted(records, key=lambda item: (item[0].page_id.value, item[0].slot_id)))

    def _members_for_workspace(self, workspace_id: int) -> tuple[WorkspaceMember, ...]:
        return self._indexed_models("workspace_members", "workspace_id", workspace_id, self._member)

    def _members_for_user(self, user_id: int) -> tuple[WorkspaceMember, ...]:
        return self._indexed_models("workspace_members", "user_id", user_id, self._member)

    def _create_membership(self, workspace_id: int, user_id: int, role: str) -> WorkspaceMember:
        self._workspace_for_id(workspace_id)
        self._user_for_id(user_id)
        self._allowed("role", role, WORKSPACE_ROLES)
        if any(member.user_id == user_id for member in self._members_for_workspace(workspace_id)):
            raise ProductConflictError(f"User {user_id} is already a workspace member.")
        member = WorkspaceMember(workspace_id, user_id, role)
        self._table("workspace_members").insert((member.workspace_id, member.user_id, member.role))
        return member

    def _workspace_owner_id(self, workspace_id: int) -> int:
        owners = [member.user_id for member in self._members_for_workspace(workspace_id) if member.role == "OWNER"]
        if len(owners) != 1:
            raise ProductValidationError(
                f"Workspace {workspace_id} must have exactly one OWNER for temporary creator attribution."
            )
        owner = self._user_for_id(owners[0])
        if owner.account_state != "ACTIVE":
            raise ProductValidationError(
                f"Workspace {workspace_id} OWNER must be ACTIVE for temporary creator attribution."
            )
        return owners[0]

    def _validate_project_creator(self, project: Project) -> None:
        self._user_for_id(project.created_by_user_id)
        self._require_membership(project.workspace_id, project.created_by_user_id, "project creator")

    def _validated_project(self, row: Tuple) -> Project:
        project = self._project(row)
        self._validate_project_creator(project)
        return project

    def _validated_task(self, row: Tuple) -> Task:
        task = self._task(row)
        project = self._project_for_id(task.project_id)
        self._user_for_id(task.created_by_user_id)
        self._require_membership(project.workspace_id, task.created_by_user_id, "task creator")
        return task

    def _require_membership(self, workspace_id: int, user_id: int, subject: str) -> None:
        if not any(member.user_id == user_id for member in self._members_for_workspace(workspace_id)):
            raise ProductPermissionError(f"User {user_id} is not a member of the workspace for this {subject}.")

    @staticmethod
    def _logical_id(value: int) -> int:
        if type(value) is not int or value < 1:
            raise ProductValidationError("Logical IDs must be positive integers.")
        return value

    @staticmethod
    def _required_text(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ProductValidationError(f"{name} must not be empty.")
        return value

    @staticmethod
    def _optional_text(name: str, value: str | None) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ProductValidationError(f"{name} must be a string or None.")
        return value

    @staticmethod
    def _allowed(name: str, value: str, allowed: frozenset[str]) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise ProductValidationError(f"Invalid {name} '{value}'.")
        return value

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0:
            raise ProductValidationError("Clock must return a non-negative integer UTC epoch millisecond timestamp.")
        return value

    def _later_than(self, current: int) -> int:
        return max(self._now(), current + 1)

    @staticmethod
    def _user(row: Tuple) -> User:
        if row[4] not in ACCOUNT_STATES:
            raise ProductValidationError(f"Invalid persisted account_state '{row[4]}'.")
        return User(row[0], row[1], row[2], row[3], row[4], row[5], row[6])

    @staticmethod
    def _workspace(row: Tuple) -> Workspace:
        if row[2] not in WORKSPACE_KINDS:
            raise ProductValidationError(f"Invalid persisted workspace kind '{row[2]}'.")
        return Workspace(row[0], row[1], row[2], row[3], row[4])

    @staticmethod
    def _member(row: Tuple) -> WorkspaceMember:
        return WorkspaceMember(row[0], row[1], row[2])

    @staticmethod
    def _project(row: Tuple) -> Project:
        return Project(row[0], row[1], row[2], row[3], row[4], row[5], row[6])

    @staticmethod
    def _task(row: Tuple) -> Task:
        if row[4] not in TASK_STATUSES:
            raise ProductValidationError(f"Invalid persisted status '{row[4]}'.")
        if row[5] not in TASK_PRIORITIES:
            raise ProductValidationError(f"Invalid persisted priority '{row[5]}'.")
        return Task(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9])

    @staticmethod
    def _note(row: Tuple) -> Note:
        return Note(row[0], row[1], row[2], row[3], row[4], row[5])
