"""Create/read/update/delete product workflow over Strata's Table APIs."""

import json
import re
from datetime import date
from typing import Callable, TypeVar

from strata_engine import StrataEngine, Tuple
from strata_engine.catalog import Table
from strata_engine.storage import RecordId

from strata_backend.product_models import (
    ACCOUNT_STATES,
    AssignedTask,
    Notification,
    TASK_PRIORITIES,
    TASK_STATUSES,
    WORKSPACE_KINDS,
    WORKSPACE_ROLES,
    Note,
    Project,
    CreatedSession,
    RegisteredAccount,
    Session,
    Task,
    TaskActivity,
    User,
    Workspace,
    WorkspaceMember,
)
from strata_backend.product_passwords import hash_password
from strata_backend.product_passwords import verify_password
from strata_backend.product_sessions import SESSION_LIFETIME_MS, generate_session_token, session_token_digest
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


class ProductRegistrationCompensationError(ProductServiceError):
    """Raised when registration's best-effort reverse compensation is incomplete."""


class ProductMembershipCompensationError(ProductServiceError):
    """Raised when a membership mutation cannot be fully compensated."""


class ProductDeletionCompensationError(ProductServiceError):
    """Raised when deleted notes or workspace memberships cannot be restored."""


ModelT = TypeVar("ModelT")


class _Unset:
    __slots__ = ()


_UNSET = _Unset()


class ProductService:
    """Application integrity boundary for Strata's initial product lifecycle.

    Database work is serialized by the engine-owned reentrant operation lock,
    shared with all services, SQL execution, catalog, tables and indexes.
    This protects validation plus mutation and logical ID allocation. It does
    not provide transactions, automatic rollback, or crash recovery.
    """

    def __init__(
        self,
        engine: StrataEngine,
        *,
        clock: Callable[[], int] = utc_epoch_milliseconds,
        token_factory: Callable[[], str] = generate_session_token,
    ) -> None:
        if not isinstance(engine, StrataEngine):
            raise TypeError(f"Expected StrataEngine, got {type(engine).__name__}.")
        if not engine.is_open:
            raise ProductServiceError("ProductService requires an open StrataEngine.")
        if not callable(clock):
            raise TypeError("clock must be callable.")
        if not callable(token_factory):
            raise TypeError("token_factory must be callable.")
        self._engine = engine
        self._lock = engine.operation()
        self._clock = clock
        self._token_factory = token_factory

    def get_user(self, user_id: int, *, actor_user_id: int | None = None) -> User:
        with self._lock:
            self._require_self(user_id, actor_user_id)
            return self._user_for_id(user_id)

    def create_session(self, user_id: int) -> CreatedSession:
        """Persist an opaque session for an existing ACTIVE user."""
        with self._lock:
            user = self._user_for_id(user_id)
            if user.account_state != "ACTIVE":
                raise ProductPermissionError("Only ACTIVE users can create sessions.")
            session, token = self._new_session(user.id, self._now())
            self._table("sessions").insert((
                session.id, session.user_id, session.token_digest,
                session.created_at, session.expires_at,
            ))
            return CreatedSession(session, token)

    def register_account(self, name: str, email: str, password: str) -> RegisteredAccount:
        """Provision an account, personal workspace, default project, and initial session.

        This is a process-local, best-effort compensating workflow, not a database
        transaction or crash-recovery mechanism.
        """
        name = self._registration_name(name)
        email = self._canonical_email(email)
        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            raise ProductValidationError(str(exc)) from exc

        with self._lock:
            if self._users_for_email(email):
                raise ProductConflictError(f"A user with email '{email}' already exists.")

            now = self._now()
            user = User(self._next_id("users"), name, email, password_hash, "ACTIVE", now, None)
            workspace = Workspace(self._next_id("workspaces"), "My Workspace", "PERSONAL", now, now)
            project = Project(self._next_id("projects"), workspace.id, "Personal", None, user.id, now, now)
            session, token = self._new_session(user.id, now)
            inserted: list[tuple[str, RecordId]] = []
            try:
                inserted.append(("users", self._registration_insert("users", (
                    user.id, user.name, user.email, user.password_hash,
                    user.account_state, user.created_at, user.deleted_at,
                ))))
                inserted.append(("workspaces", self._registration_insert("workspaces", (
                    workspace.id, workspace.name, workspace.kind,
                    workspace.created_at, workspace.updated_at,
                ))))
                inserted.append(("workspace_members", self._registration_insert("workspace_members", (
                    workspace.id, user.id, "OWNER",
                ))))
                inserted.append(("projects", self._registration_insert("projects", (
                    project.id, project.workspace_id, project.name, project.description,
                    project.created_by_user_id, project.created_at, project.updated_at,
                ))))
                inserted.append(("sessions", self._registration_insert("sessions", (
                    session.id, session.user_id, session.token_digest,
                    session.created_at, session.expires_at,
                ))))
            except Exception as exc:
                if self._compensate_registration(inserted):
                    raise ProductRegistrationCompensationError(
                        "Registration compensation did not complete successfully."
                    ) from exc
                raise
            return RegisteredAccount(user, workspace, project, session, token)

    def authenticate_user(self, email: str, password: str) -> CreatedSession | None:
        """Verify credentials outside the lock, then create a session if still ACTIVE."""
        try:
            canonical_email = self._canonical_email(email)
        except ProductValidationError:
            return None

        with self._lock:
            users = self._users_for_email(canonical_email)
            user = users[0] if len(users) == 1 else None
            if user is None or user.account_state != "ACTIVE" or user.password_hash is None:
                return None
            password_hash = user.password_hash

        if not verify_password(password_hash, password):
            return None
        try:
            return self.create_session(user.id)
        except (ProductNotFoundError, ProductPermissionError):
            return None

    def find_session_by_token(self, token: str) -> Session | None:
        """Resolve an unexpired persisted session by its raw opaque token."""
        try:
            digest = session_token_digest(token)
        except ValueError:
            return None
        with self._lock:
            records = self._indexed_records("sessions", "token_digest", digest)
            if not records:
                return None
            session = self._session(records[0][1])
            if session.expires_at <= self._now():
                try:
                    self._table("sessions").delete(records[0][0])
                except Exception:
                    pass
                return None
            return session

    def revoke_session_by_token(self, token: str) -> None:
        """Resolve and revoke atomically; numeric session IDs may be reused."""
        with self._lock:
            session = self.find_session_by_token(token)
            if session is not None:
                self.revoke_session(session.id)

    def revoke_session(self, session_id: int) -> None:
        """Delete one exact persisted session by logical ID."""
        with self._lock:
            record_id, _ = self._record_or_not_found("sessions", session_id)
            self._table("sessions").delete(record_id)

    def get_workspace(self, workspace_id: int, *, actor_user_id: int | None = None) -> Workspace:
        with self._lock:
            workspace = self._workspace_for_id(workspace_id)
            self._require_visible(workspace.id, actor_user_id)
            return workspace

    def list_workspaces_for_user(self, user_id: int, *, actor_user_id: int | None = None) -> tuple[Workspace, ...]:
        with self._lock:
            self._require_self(user_id, actor_user_id)
            self._user_for_id(user_id)
            workspace_ids = {member.workspace_id for member in self._members_for_user(user_id)}
            return tuple(sorted((self._workspace_for_id(item) for item in workspace_ids), key=lambda item: item.id))

    def list_workspace_members(self, workspace_id: int, *, actor_user_id: int | None = None) -> tuple[WorkspaceMember, ...]:
        with self._lock:
            self._workspace_for_id(workspace_id)
            self._require_visible(workspace_id, actor_user_id)
            return tuple(sorted(self._members_for_workspace(workspace_id), key=lambda item: (item.user_id, item.role)))

    def add_workspace_member(self, workspace_id: int, user_id: int, *, actor_user_id: int | None = None) -> WorkspaceMember:
        with self._lock:
            workspace = self._workspace_for_id(workspace_id)
            self._require_owner(workspace, actor_user_id)
            self._require_collaborative(workspace)
            user = self._user_for_id(user_id)
            if user.account_state != "ACTIVE":
                raise ProductConflictError("Only ACTIVE users can be added to a workspace.")
            return self._create_membership(workspace_id, user_id, "MEMBER", actor_user_id=actor_user_id)

    def add_workspace_member_by_email(self, workspace_id: int, email: str, *, actor_user_id: int | None = None) -> WorkspaceMember:
        """Add an existing registered user to a workspace by normalized email."""
        with self._lock:
            workspace = self._workspace_for_id(workspace_id)
            self._require_owner(workspace, actor_user_id)
            self._require_collaborative(workspace)
            canonical_email = self._canonical_email(email)
            users = self._users_for_email(canonical_email)
            if not users:
                raise ProductNotFoundError(f"No registered user has email '{canonical_email}'.")
            return self.add_workspace_member(workspace_id, users[0].id, actor_user_id=actor_user_id)

    def transfer_workspace_ownership(self, workspace_id: int, new_owner_user_id: int, *, actor_user_id: int | None = None) -> tuple[int, int]:
        with self._lock:
            workspace = self._workspace_for_id(workspace_id)
            self._require_owner(workspace, actor_user_id)
            self._require_collaborative(workspace)
            current_owner_id = self._workspace_owner_id(workspace_id)
            new_owner = self._user_for_id(new_owner_user_id)
            if new_owner.id == current_owner_id or new_owner.account_state != "ACTIVE":
                raise ProductConflictError("New owner must be a different ACTIVE workspace MEMBER.")
            records = self._indexed_records("workspace_members", "workspace_id", workspace_id)
            by_user = {self._member(row).user_id: (record_id, row) for record_id, row in records}
            target = by_user.get(new_owner.id)
            current = by_user.get(current_owner_id)
            if target is None or self._member(target[1]).role != "MEMBER" or current is None:
                raise ProductConflictError("New owner must be a workspace MEMBER.")
            current_record_id = current[0]
            try:
                # OWNER -> MEMBER grows the row and can relocate it on a full page.
                current_record_id = self._set_membership_role(current_record_id, current[1], "MEMBER")
                self._set_membership_role(target[0], target[1], "OWNER")
            except Exception as exc:
                failed = False
                try:
                    self._set_membership_role(current_record_id, current[1], "OWNER")
                except Exception:
                    failed = True
                try:
                    self._set_membership_role(target[0], target[1], "MEMBER")
                except Exception:
                    failed = True
                if failed:
                    raise ProductMembershipCompensationError("Ownership transfer compensation did not complete successfully.") from exc
                raise
            return current_owner_id, new_owner.id

    def remove_workspace_member(self, workspace_id: int, user_id: int, *, actor_user_id: int | None = None) -> None:
        with self._lock:
            workspace = self._workspace_for_id(workspace_id)
            self._require_owner(workspace, actor_user_id)
            self._require_collaborative(workspace)
            self._user_for_id(user_id)
            member_records = self._indexed_records("workspace_members", "workspace_id", workspace_id)
            member_record = next(((record_id, row) for record_id, row in member_records if self._member(row).user_id == user_id), None)
            if member_record is None:
                raise ProductNotFoundError("Workspace member does not exist.")
            if self._member(member_record[1]).role == "OWNER":
                raise ProductConflictError("Transfer ownership before removing the workspace OWNER.")
            changed: list[tuple[RecordId, Tuple]] = []
            activity_record_ids: list[RecordId] = []
            membership_deleted = False
            notification_record_id: RecordId | None = None
            actor_id = self._workspace_owner_id(workspace_id) if actor_user_id is None else actor_user_id
            try:
                for project_record_id, project_row in self._indexed_records("projects", "workspace_id", workspace_id):
                    del project_record_id
                    project = self._validated_project(project_row)
                    for task_record_id, task_row in self._indexed_records("tasks", "project_id", project.id):
                        task = self._validated_task(task_row)
                        if task.assignee_user_id == user_id:
                            changed.append((task_record_id, task_row))
                            self._unassign_task(task_record_id, task_row)
                            activity_record_ids.append(self._append_activity(
                                task, workspace_id, actor_id, "ASSIGNEE_CHANGED",
                                {"field": "assignee_user_id", "from": user_id, "to": None, "reason": "membership_removed"},
                            ))
                self._delete_membership(member_record[0])
                membership_deleted = True
                notification_record_id = self._create_notification(
                    user_id, actor_user_id, "WORKSPACE_REMOVED",
                    "Your access to a workspace was removed.", None, None, None,
                )
            except Exception as exc:
                failed = False
                if notification_record_id is not None:
                    try:
                        self._table("notifications").delete(notification_record_id)
                    except Exception:
                        failed = True
                for activity_record_id in reversed(activity_record_ids):
                    try:
                        self._table("task_activity").delete(activity_record_id)
                    except Exception:
                        failed = True
                if membership_deleted:
                    try:
                        self._table("workspace_members").insert(member_record[1])
                    except Exception:
                        failed = True
                for task_record_id, task_row in reversed(changed):
                    try:
                        self._table("tasks").update(task_record_id, task_row)
                    except Exception:
                        failed = True
                if failed:
                    raise ProductMembershipCompensationError("Member removal compensation did not complete successfully.") from exc
                raise

    def get_project(self, project_id: int, *, actor_user_id: int | None = None) -> Project:
        with self._lock:
            project = self._project_for_id(project_id)
            self._require_visible(project.workspace_id, actor_user_id)
            return project

    def list_projects(self, workspace_id: int, *, actor_user_id: int | None = None) -> tuple[Project, ...]:
        with self._lock:
            self._workspace_for_id(workspace_id)
            self._require_visible(workspace_id, actor_user_id)
            return tuple(sorted((self._validated_project(row) for _, row in self._indexed_records("projects", "workspace_id", workspace_id)), key=lambda item: item.id))

    def get_task(self, task_id: int, *, actor_user_id: int | None = None) -> Task:
        with self._lock:
            task = self._task_for_id(task_id)
            self._require_visible(self._project_for_id(task.project_id).workspace_id, actor_user_id)
            return task

    def list_tasks(
        self, project_id: int, *, actor_user_id: int | None = None,
        query: str | None = None, status: str | None = None,
        priority: str | None = None, due_before: str | None = None,
        due_after: str | None = None, sort: str = "id", limit: int = 200,
        offset: int = 0,
    ) -> tuple[Task, ...]:
        with self._lock:
            project = self._project_for_id(project_id)
            self._require_visible(project.workspace_id, actor_user_id)
            tasks = [self._validated_task(row) for _, row in self._indexed_records("tasks", "project_id", project_id)]
            tasks = self._filter_tasks(tasks, query=query, status=status, priority=priority, due_before=due_before, due_after=due_after)
            return tuple(self._sort_tasks(tasks, sort)[self._offset(offset):self._offset(offset) + self._limit(limit, 200)])

    def list_assigned_tasks(
        self, *, actor_user_id: int, query: str | None = None,
        status: str | None = None, priority: str | None = None,
        due_before: str | None = None, due_after: str | None = None,
        workspace_id: int | None = None, project_id: int | None = None,
        sort: str = "updated_desc", limit: int = 50, offset: int = 0,
    ) -> tuple[tuple[AssignedTask, ...], int]:
        """Return a bounded membership-filtered view of the authenticated user's work."""
        with self._lock:
            self._user_for_id(actor_user_id)
            allowed_workspace_ids = {member.workspace_id for member in self._members_for_user(actor_user_id)}
            if workspace_id is not None:
                self._logical_id(workspace_id)
                self._require_visible(workspace_id, actor_user_id)
                allowed_workspace_ids &= {workspace_id}
            projects: dict[int, Project] = {}
            workspaces: dict[int, Workspace] = {}
            for allowed_id in sorted(allowed_workspace_ids):
                workspace = self._workspace_for_id(allowed_id)
                workspaces[allowed_id] = workspace
                for project in self.list_projects(allowed_id, actor_user_id=actor_user_id):
                    if project_id is None or project.id == project_id:
                        projects[project.id] = project
            assigned = [
                self._validated_task(row)
                for _, row in self._indexed_records("tasks", "assignee_user_id", actor_user_id)
                if row[1] in projects
            ]
            filtered = self._filter_tasks(assigned, query=query, status=status, priority=priority, due_before=due_before, due_after=due_after)
            ordered = self._sort_tasks(filtered, sort)
            start = self._offset(offset)
            page = ordered[start:start + self._limit(limit, 100)]
            return tuple(
                AssignedTask(task, projects[task.project_id].name, projects[task.project_id].workspace_id, workspaces[projects[task.project_id].workspace_id].name, None if task.assignee_user_id is None else self._user_for_id(task.assignee_user_id).name)
                for task in page
            ), len(filtered)

    def list_accessible_tasks(
        self, *, actor_user_id: int, query: str | None = None,
        status: str | None = None, priority: str | None = None,
        due_before: str | None = None, due_after: str | None = None,
        workspace_id: int | None = None, project_id: int | None = None,
        sort: str = "updated_desc", limit: int = 50, offset: int = 0,
    ) -> tuple[tuple[AssignedTask, ...], int]:
        """Return a paginated account-wide task view limited to active memberships."""
        with self._lock:
            self._user_for_id(actor_user_id)
            allowed_workspace_ids = {member.workspace_id for member in self._members_for_user(actor_user_id)}
            if workspace_id is not None:
                self._logical_id(workspace_id)
                self._require_visible(workspace_id, actor_user_id)
                allowed_workspace_ids &= {workspace_id}
            projects: dict[int, Project] = {}
            workspaces: dict[int, Workspace] = {}
            for allowed_id in sorted(allowed_workspace_ids):
                workspace = self._workspace_for_id(allowed_id)
                workspaces[allowed_id] = workspace
                for project in self.list_projects(allowed_id, actor_user_id=actor_user_id):
                    if project_id is None or project.id == project_id:
                        projects[project.id] = project
            tasks = [
                self._validated_task(row)
                for project_id_value in sorted(projects)
                for _, row in self._indexed_records("tasks", "project_id", project_id_value)
            ]
            filtered = self._filter_tasks(tasks, query=query, status=status, priority=priority, due_before=due_before, due_after=due_after)
            ordered = self._sort_tasks(filtered, sort)
            start = self._offset(offset)
            page = ordered[start:start + self._limit(limit, 100)]
            return tuple(
                AssignedTask(task, projects[task.project_id].name, projects[task.project_id].workspace_id, workspaces[projects[task.project_id].workspace_id].name, None if task.assignee_user_id is None else self._user_for_id(task.assignee_user_id).name)
                for task in page
            ), len(filtered)

    def dashboard(self, *, actor_user_id: int, workspace_id: int | None = None) -> dict[str, object]:
        """Compute membership-filtered dashboard metrics for an account or workspace."""
        with self._lock:
            workspaces = list(self.list_workspaces_for_user(actor_user_id, actor_user_id=actor_user_id))
            if workspace_id is not None:
                self._require_visible(workspace_id, actor_user_id)
                workspaces = [workspace for workspace in workspaces if workspace.id == workspace_id]
            projects = [
                project
                for workspace in workspaces
                for project in self.list_projects(workspace.id, actor_user_id=actor_user_id)
            ]
            tasks = [
                self._validated_task(row)
                for project in projects
                for _, row in self._indexed_records("tasks", "project_id", project.id)
            ]
            today = date.today().isoformat()
            dated = [task for task in tasks if task.due_date is not None and task.status != "DONE"]
            return {
                "scope": "workspace" if workspace_id is not None else "account",
                "workspace_id": workspace_id,
                "workspace_count": len(workspaces),
                "project_count": len(projects),
                "task_count": len(tasks),
                "assigned_to_me": sum(task.assignee_user_id == actor_user_id for task in tasks),
                "overdue_count": sum(task.due_date < today for task in dated if task.due_date is not None),
                "upcoming_count": sum(task.due_date >= today for task in dated if task.due_date is not None),
                "completed_count": sum(task.status == "DONE" for task in tasks),
                "status_counts": {value: sum(task.status == value for task in tasks) for value in sorted(TASK_STATUSES)},
                "priority_counts": {value: sum(task.priority == value for task in tasks) for value in sorted(TASK_PRIORITIES)},
            }

    def list_task_activity(
        self, task_id: int, *, actor_user_id: int,
        limit: int = 50, offset: int = 0,
    ) -> tuple[tuple[TaskActivity, ...], int]:
        with self._lock:
            self._logical_id(task_id)
            events = sorted(
                self._indexed_models("task_activity", "task_id", task_id, self._activity),
                key=lambda item: (item.created_at, item.id), reverse=True,
            )
            found = self._find("tasks", task_id)
            if found is None:
                if not events:
                    raise ProductNotFoundError(f"Task {task_id} does not exist.")
                identities = {(event.project_id, event.workspace_id) for event in events}
                if len(identities) != 1:
                    raise ProductValidationError("Task activity has inconsistent workspace identity and cannot be repaired unambiguously.")
                self._require_visible(next(iter(identities))[1], actor_user_id)
            else:
                task = self._validated_task(found[1])
                project = self._project_for_id(task.project_id)
                self._require_visible(project.workspace_id, actor_user_id)
                matching = [event for event in events if event.workspace_id == project.workspace_id and event.project_id == task.project_id]
                mismatched = [event for event in events if event not in matching]
                if mismatched:
                    matching_created = [event for event in matching if event.event_type == "TASK_CREATED"]
                    boundary = matching_created[0] if len(matching_created) == 1 else None
                    older = [] if boundary is None else [
                        event for event in mismatched
                        if (event.created_at, event.id) < (boundary.created_at, boundary.id)
                    ]
                    if boundary is None or len(older) != len(mismatched) or not any(event.event_type == "TASK_DELETED" for event in older):
                        raise ProductValidationError("Task activity has inconsistent workspace identity and cannot be repaired unambiguously.")
                    events = matching
            start = self._offset(offset)
            return tuple(events[start:start + self._limit(limit, 100)]), len(events)

    def list_notifications(
        self, *, actor_user_id: int, unread_only: bool = False,
        limit: int = 50, offset: int = 0,
    ) -> tuple[tuple[Notification, ...], int]:
        with self._lock:
            self._user_for_id(actor_user_id)
            notifications = [
                self._safe_notification(self._notification(row), actor_user_id)
                for _, row in self._indexed_records("notifications", "recipient_user_id", actor_user_id)
            ]
            visible = [item for item in notifications if item is not None and item.dismissed_at is None and (not unread_only or not item.is_read)]
            visible.sort(key=lambda item: (item.created_at, item.id), reverse=True)
            start = self._offset(offset)
            return tuple(visible[start:start + self._limit(limit, 100)]), len(visible)

    def unread_notification_count(self, *, actor_user_id: int) -> int:
        return self.list_notifications(actor_user_id=actor_user_id, unread_only=True, limit=1)[1]

    def set_notification_read(self, notification_id: int, is_read: bool, *, actor_user_id: int) -> Notification:
        with self._lock:
            record_id, row = self._record_or_not_found("notifications", notification_id)
            current = self._notification(row)
            if current.recipient_user_id != actor_user_id:
                raise ProductNotFoundError("Notification does not exist.")
            if self._safe_notification(current, actor_user_id) is None:
                raise ProductNotFoundError("Notification does not exist.")
            if type(is_read) is not bool:
                raise ProductValidationError("is_read must be a boolean.")
            updated = Notification(current.id, current.recipient_user_id, current.event_type, current.summary, current.workspace_id, current.project_id, current.task_id, current.created_at, is_read, current.dismissed_at)
            if updated != current:
                self._table("notifications").update(record_id, Tuple(self._notification_values(updated), schema=row.schema))
            safe = self._safe_notification(updated, actor_user_id)
            if safe is None:
                raise ProductNotFoundError("Notification does not exist.")
            return safe

    def mark_all_notifications_read(self, *, actor_user_id: int) -> int:
        with self._lock:
            changed = 0
            for record_id, row in self._indexed_records("notifications", "recipient_user_id", actor_user_id):
                item = self._notification(row)
                if item.dismissed_at is None and not item.is_read and self._safe_notification(item, actor_user_id) is not None:
                    updated = Notification(item.id, item.recipient_user_id, item.event_type, item.summary, item.workspace_id, item.project_id, item.task_id, item.created_at, True, item.dismissed_at)
                    self._table("notifications").update(record_id, Tuple(self._notification_values(updated), schema=row.schema))
                    changed += 1
            return changed

    def dismiss_notification(self, notification_id: int, *, actor_user_id: int) -> None:
        with self._lock:
            record_id, row = self._record_or_not_found("notifications", notification_id)
            item = self._notification(row)
            if item.recipient_user_id != actor_user_id or self._safe_notification(item, actor_user_id) is None:
                raise ProductNotFoundError("Notification does not exist.")
            updated = Notification(item.id, item.recipient_user_id, item.event_type, item.summary, item.workspace_id, item.project_id, item.task_id, item.created_at, item.is_read, self._now())
            self._table("notifications").update(record_id, Tuple(self._notification_values(updated), schema=row.schema))

    def get_note(self, note_id: int, *, actor_user_id: int | None = None) -> Note:
        with self._lock:
            note = self._note_for_id(note_id)
            self._require_visible(self._workspace_for_note(note).id, actor_user_id)
            return note

    def list_notes(self, task_id: int, *, actor_user_id: int | None = None) -> tuple[Note, ...]:
        with self._lock:
            task = self._task_for_id(task_id)
            self._require_visible(self._project_for_id(task.project_id).workspace_id, actor_user_id)
            return tuple(sorted(self._indexed_models("notes", "task_id", task_id, self._note), key=lambda item: item.id))

    def create_user(self, name: str, email: str) -> User:
        with self._lock:
            name = self._required_text("name", name)
            email = self._canonical_email(email)
            if self._users_for_email(email):
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
            inserted: list[tuple[str, RecordId]] = []
            try:
                inserted.append(("workspaces", self._registration_insert("workspaces", (
                    workspace.id, workspace.name, workspace.kind,
                    workspace.created_at, workspace.updated_at,
                ))))
                inserted.append(("workspace_members", self._registration_insert("workspace_members", (
                    workspace.id, owner_user_id, "OWNER",
                ))))
            except Exception as exc:
                if self._compensate_registration(inserted):
                    raise ProductRegistrationCompensationError("Workspace provisioning compensation did not complete successfully.") from exc
                raise
            return workspace

    def create_project(self, workspace_id: int, name: str, description: str | None = None, *, actor_user_id: int | None = None) -> Project:
        with self._lock:
            self._workspace_for_id(workspace_id)
            self._require_visible(workspace_id, actor_user_id)
            name = self._required_text("name", name)
            description = self._optional_text("description", description)
            creator_id = self._workspace_owner_id(workspace_id) if actor_user_id is None else actor_user_id
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
        due_date: str | None = None,
        *,
        actor_user_id: int | None = None,
    ) -> Task:
        with self._lock:
            project = self._project_for_id(project_id)
            self._require_visible(project.workspace_id, actor_user_id)
            title = self._required_text("title", title)
            description = self._optional_text("description", description)
            self._allowed("status", status, TASK_STATUSES)
            self._allowed("priority", priority, TASK_PRIORITIES)
            if assignee_user_id is not None:
                self._user_for_id(assignee_user_id)
                self._require_membership(project.workspace_id, assignee_user_id, "assignee")
            due_date = self._validated_due_date(due_date)
            actor_id = project.created_by_user_id if actor_user_id is None else actor_user_id
            now = self._now()
            task = Task(
                self._next_task_id(), project_id, title, description, status, priority,
                assignee_user_id, actor_id, now, now, due_date,
            )
            inserted: list[tuple[str, RecordId]] = []
            try:
                inserted.append(("tasks", self._table("tasks").insert(self._task_values(task))))
                if due_date is not None:
                    inserted.append(("task_due_dates", self._table("task_due_dates").insert((task.id, due_date))))
                inserted.append(("task_activity", self._append_activity(
                    task, project.workspace_id, actor_id, "TASK_CREATED",
                    {"status": status, "priority": priority, "due_date": due_date},
                )))
                if assignee_user_id is not None:
                    notification_id = self._create_notification(
                        assignee_user_id, actor_id, "TASK_ASSIGNED", "A task was assigned to you.",
                        project.workspace_id, project.id, task.id,
                    )
                    if notification_id is not None:
                        inserted.append(("notifications", notification_id))
            except Exception as exc:
                if self._compensate_registration(inserted):
                    raise ProductRegistrationCompensationError("Task creation compensation did not complete successfully.") from exc
                raise
            return task

    def create_note(self, task_id: int, author_user_id: int, content: str, *, actor_user_id: int | None = None) -> Note:
        with self._lock:
            task = self._task_for_id(task_id)
            self._user_for_id(author_user_id)
            project = self._project_for_id(task.project_id)
            self._require_visible(project.workspace_id, actor_user_id)
            if actor_user_id is not None and author_user_id != actor_user_id:
                raise ProductPermissionError("Note author must be the authenticated user.")
            self._require_membership(project.workspace_id, author_user_id, "note author")
            now = self._now()
            note = Note(self._next_id("notes"), task_id, author_user_id, self._required_text("content", content), now, now)
            self._table("notes").insert((
                note.id, note.task_id, note.author_user_id, note.content,
                note.created_at, note.updated_at,
            ))
            return note

    def update_user(self, user_id: int, *, actor_user_id: int | None = None, name: str | _Unset = _UNSET, email: str | _Unset = _UNSET) -> User:
        with self._lock:
            self._require_self(user_id, actor_user_id)
            record_id, row = self._record_or_not_found("users", user_id)
            current = self._user(row)
            next_name = current.name if name is _UNSET else self._required_text("name", name)
            next_email = current.email if email is _UNSET else self._canonical_email(email)
            if email is not _UNSET and any(user.id != current.id for user in self._users_for_email(next_email)):
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

    def update_workspace(self, workspace_id: int, *, actor_user_id: int | None = None, name: str | _Unset = _UNSET) -> Workspace:
        with self._lock:
            record_id, row = self._record_or_not_found("workspaces", workspace_id)
            current = self._workspace(row)
            self._require_owner(current, actor_user_id)
            if current.kind == "PERSONAL" and actor_user_id is not None:
                raise ProductPermissionError("Personal workspaces cannot be modified.")
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
        self, project_id: int, *, actor_user_id: int | None = None, name: str | _Unset = _UNSET, description: str | None | _Unset = _UNSET,
    ) -> Project:
        with self._lock:
            record_id, row = self._record_or_not_found("projects", project_id)
            current = self._validated_project(row)
            self._require_visible(current.workspace_id, actor_user_id)
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
        due_date: str | None | _Unset = _UNSET,
        handoff_note: str | None | _Unset = _UNSET,
        actor_user_id: int | None = None,
    ) -> Task:
        with self._lock:
            record_id, row = self._record_or_not_found("tasks", task_id)
            current = self._validated_task(row)
            project = self._project_for_id(current.project_id)
            self._require_visible(project.workspace_id, actor_user_id)
            actor_id = current.created_by_user_id if actor_user_id is None else actor_user_id
            next_title = current.title if title is _UNSET else self._required_text("title", title)
            next_description = current.description if description is _UNSET else self._optional_text("description", description)
            next_status = current.status if status is _UNSET else self._allowed("status", status, TASK_STATUSES)
            next_priority = current.priority if priority is _UNSET else self._allowed("priority", priority, TASK_PRIORITIES)
            next_assignee = current.assignee_user_id if assignee_user_id is _UNSET else assignee_user_id
            next_due_date = current.due_date if due_date is _UNSET else self._validated_due_date(due_date)
            if next_assignee is not None:
                self._user_for_id(next_assignee)
                self._require_membership(project.workspace_id, next_assignee, "assignee")
            assignment_changed = next_assignee != current.assignee_user_id
            if handoff_note is not _UNSET:
                if not assignment_changed:
                    raise ProductValidationError("handoff_note requires an assignee change.")
                handoff_note = self._bounded_optional_text("handoff_note", handoff_note, 1000)
                if handoff_note is None or not handoff_note.strip():
                    raise ProductValidationError("handoff_note must not be empty when supplied.")
            changed = (
                next_title != current.title or next_description != current.description
                or next_status != current.status or next_priority != current.priority
                or next_assignee != current.assignee_user_id
                or next_due_date != current.due_date
            )
            updated = Task(
                current.id, current.project_id, next_title, next_description, next_status,
                next_priority, next_assignee, current.created_by_user_id, current.created_at,
                current.updated_at if not changed else self._later_than(current.updated_at),
                next_due_date,
            )
            if not changed:
                return updated
            inserted: list[tuple[str, RecordId]] = []
            updated_record_id = record_id
            old_due = current.due_date
            due_changed = next_due_date != old_due
            try:
                updated_record_id = self._table("tasks").update(record_id, Tuple(self._task_values(updated), schema=row.schema))
                if due_changed:
                    self._set_due_date(task_id, next_due_date)
                changes = (
                    ("title", current.title, updated.title, "TITLE_CHANGED"),
                    ("description", current.description, updated.description, "DESCRIPTION_CHANGED"),
                    ("status", current.status, updated.status,
                     "TASK_COMPLETED" if current.status != "DONE" and updated.status == "DONE" else
                     "TASK_REOPENED" if current.status == "DONE" and updated.status != "DONE" else "STATUS_CHANGED"),
                    ("priority", current.priority, updated.priority, "PRIORITY_CHANGED"),
                    ("assignee_user_id", current.assignee_user_id, updated.assignee_user_id, "ASSIGNEE_CHANGED"),
                    ("due_date", current.due_date, updated.due_date, "DUE_DATE_CHANGED"),
                )
                for field, old, new, event_type in changes:
                    if old != new:
                        details: dict[str, object] = {"field": field, "from": old, "to": new}
                        if field == "assignee_user_id" and handoff_note is not _UNSET:
                            details["handoff_note"] = handoff_note
                        inserted.append(("task_activity", self._append_activity(
                            updated, project.workspace_id, actor_id, event_type, details,
                        )))
                recipients: list[tuple[int, str, str]] = []
                if assignment_changed:
                    if current.assignee_user_id is not None:
                        recipients.append((current.assignee_user_id, "TASK_REASSIGNED_AWAY", "A task was reassigned away from you."))
                    if next_assignee is not None:
                        recipients.append((next_assignee, "TASK_HANDOFF" if handoff_note is not _UNSET else "TASK_ASSIGNED", "A task was handed off to you." if handoff_note is not _UNSET else "A task was assigned to you."))
                elif next_assignee is not None:
                    recipients.append((next_assignee, "TASK_CHANGED", "An assigned task was updated."))
                for recipient, event_type, summary in recipients:
                    notification_id = self._create_notification(recipient, actor_id, event_type, summary, project.workspace_id, project.id, task_id)
                    if notification_id is not None:
                        inserted.append(("notifications", notification_id))
            except Exception as exc:
                failed = self._compensate_registration(inserted)
                try:
                    if due_changed:
                        self._set_due_date(task_id, old_due)
                    self._table("tasks").update(updated_record_id, row)
                except Exception:
                    failed = True
                if failed:
                    raise ProductRegistrationCompensationError("Task update compensation did not complete successfully.") from exc
                raise
            return updated

    def update_note(self, note_id: int, *, actor_user_id: int | None = None, content: str | _Unset = _UNSET) -> Note:
        with self._lock:
            record_id, row = self._record_or_not_found("notes", note_id)
            current = self._note(row)
            self._require_note_author(current, actor_user_id)
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

    def delete_note(self, note_id: int, *, actor_user_id: int | None = None) -> None:
        with self._lock:
            record_id, row = self._record_or_not_found("notes", note_id)
            self._require_note_author(self._note(row), actor_user_id)
            self._table("notes").delete(record_id)

    def delete_task(self, task_id: int, *, actor_user_id: int | None = None) -> None:
        with self._lock:
            record_id, row = self._record_or_not_found("tasks", task_id)
            task = self._validated_task(row)
            project = self._project_for_id(task.project_id)
            self._require_creator_or_owner_fallback(project.workspace_id, task.created_by_user_id, actor_user_id)
            actor_id = task.created_by_user_id if actor_user_id is None else actor_user_id
            note_records = self._indexed_records("notes", "task_id", task_id)
            due_records = self._indexed_records("task_due_dates", "task_id", task_id)
            deleted_notes: list[Tuple] = []
            deleted_due: list[Tuple] = []
            activity_record_id: RecordId | None = None
            task_deleted = False
            try:
                for note_record_id, note_row in note_records:
                    self._table("notes").delete(note_record_id)
                    deleted_notes.append(note_row)
                for due_record_id, due_row in due_records:
                    self._table("task_due_dates").delete(due_record_id)
                    deleted_due.append(due_row)
                self._table("tasks").delete(record_id)
                task_deleted = True
                activity_record_id = self._append_activity(
                    task, project.workspace_id, actor_id, "TASK_DELETED", None,
                )
            except Exception as exc:
                failed = False
                if activity_record_id is not None:
                    try:
                        self._table("task_activity").delete(activity_record_id)
                    except Exception:
                        failed = True
                if task_deleted:
                    try:
                        self._table("tasks").insert(row)
                    except Exception:
                        failed = True
                for due_row in reversed(deleted_due):
                    try:
                        self._table("task_due_dates").insert(due_row)
                    except Exception:
                        failed = True
                for note_row in reversed(deleted_notes):
                    try:
                        self._table("notes").insert(note_row)
                    except Exception:
                        failed = True
                if failed:
                    raise ProductDeletionCompensationError("Task deletion compensation did not complete successfully.") from exc
                raise

    def delete_project(self, project_id: int, *, actor_user_id: int | None = None) -> None:
        with self._lock:
            record_id, row = self._record_or_not_found("projects", project_id)
            project = self._validated_project(row)
            self._require_creator_or_owner_fallback(project.workspace_id, project.created_by_user_id, actor_user_id)
            if self._indexed_records("tasks", "project_id", project_id):
                raise ProductConflictError("Cannot delete a project that still has tasks.")
            self._table("projects").delete(record_id)

    def delete_workspace(self, workspace_id: int, *, actor_user_id: int | None = None) -> None:
        with self._lock:
            record_id, row = self._record_or_not_found("workspaces", workspace_id)
            workspace = self._workspace(row)
            self._require_owner(workspace, actor_user_id)
            if workspace.kind == "PERSONAL" and actor_user_id is not None:
                raise ProductPermissionError("Personal workspaces cannot be deleted.")
            if self._indexed_records("projects", "workspace_id", workspace_id):
                raise ProductConflictError("Cannot delete a workspace that still has projects.")
            member_records = self._indexed_records("workspace_members", "workspace_id", workspace_id)
            activity_records = self._indexed_records("task_activity", "workspace_id", workspace_id)
            notification_records = self._indexed_records("notifications", "workspace_id", workspace_id)
            deleted: list[tuple[str, Tuple]] = []
            workspace_deleted = False
            try:
                for member_record_id, member_row in member_records:
                    self._table("workspace_members").delete(member_record_id)
                    deleted.append(("workspace_members", member_row))
                for activity_record_id, activity_row in activity_records:
                    self._table("task_activity").delete(activity_record_id)
                    deleted.append(("task_activity", activity_row))
                for notification_record_id, notification_row in notification_records:
                    self._table("notifications").delete(notification_record_id)
                    deleted.append(("notifications", notification_row))
                self._table("workspaces").delete(record_id)
                workspace_deleted = True
            except Exception as exc:
                failed = False
                if workspace_deleted:
                    try:
                        self._table("workspaces").insert(row)
                    except Exception:
                        failed = True
                for table_name, deleted_row in reversed(deleted):
                    try:
                        self._table(table_name).insert(deleted_row)
                    except Exception:
                        failed = True
                if failed:
                    raise ProductDeletionCompensationError("Workspace deletion compensation did not complete successfully.") from exc
                raise

    def _table(self, name: str) -> Table:
        if not self._engine.is_open:
            raise ProductServiceError("ProductService cannot use a closed StrataEngine.")
        return self._engine.get_table(name)

    def _registration_insert(self, table_name: str, values: tuple[object, ...]) -> RecordId:
        """Focused persistence seam for the registration workflow."""
        return self._table(table_name).insert(values)

    def _registration_delete(self, table_name: str, record_id: RecordId) -> None:
        """Focused inverse-persistence seam for registration compensation."""
        self._table(table_name).delete(record_id)

    def _compensate_registration(self, inserted: list[tuple[str, RecordId]]) -> bool:
        """Attempt every inverse in reverse write order; return whether any failed."""
        failed = False
        for table_name, record_id in reversed(inserted):
            try:
                self._registration_delete(table_name, record_id)
            except Exception:
                failed = True
        return failed

    def _next_id(self, table_name: str) -> int:
        values = [row[0] for _, row in self._table(table_name).scan()]
        return 1 if not values else max(values) + 1

    def _next_task_id(self) -> int:
        """Allocate beyond live and retained audit identities."""
        values = [row[0] for _, row in self._table("tasks").scan()]
        values.extend(row[1] for _, row in self._table("task_activity").scan())
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

    def _users_for_email(self, email: str) -> tuple[User, ...]:
        return tuple(self._user(row) for _, row in self._indexed_records("users", "email", email))

    def _new_session(self, user_id: int, now: int) -> tuple[Session, str]:
        """Allocate session metadata and raw token under the service lock."""
        for _ in range(3):
            token = self._token_factory()
            try:
                digest = session_token_digest(token)
            except ValueError as exc:
                raise ProductValidationError(str(exc)) from exc
            if self._indexed_records("sessions", "token_digest", digest):
                continue
            return (
                Session(self._next_id("sessions"), user_id, digest, now, now + SESSION_LIFETIME_MS),
                token,
            )
        raise ProductConflictError("Could not allocate a unique session token.")

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

    def _create_membership(
        self, workspace_id: int, user_id: int, role: str,
        *, actor_user_id: int | None = None,
    ) -> WorkspaceMember:
        workspace = self._workspace_for_id(workspace_id)
        self._require_collaborative(workspace)
        user = self._user_for_id(user_id)
        if user.account_state != "ACTIVE":
            raise ProductConflictError("Only ACTIVE users can be added to a workspace.")
        self._allowed("role", role, WORKSPACE_ROLES)
        if any(member.user_id == user_id for member in self._members_for_workspace(workspace_id)):
            raise ProductConflictError(f"User {user_id} is already a workspace member.")
        member = WorkspaceMember(workspace_id, user_id, role)
        member_record_id = self._table("workspace_members").insert((member.workspace_id, member.user_id, member.role))
        try:
            self._create_notification(
                user_id, actor_user_id, "WORKSPACE_ADDED",
                "You were added to a workspace.", workspace_id, None, None,
            )
        except Exception:
            self._table("workspace_members").delete(member_record_id)
            raise
        return member

    def _set_membership_role(self, record_id: RecordId, row: Tuple, role: str) -> RecordId:
        member = self._member(row)
        return self._table("workspace_members").update(
            record_id, Tuple((member.workspace_id, member.user_id, role), schema=row.schema),
        )

    def _delete_membership(self, record_id: RecordId) -> None:
        self._table("workspace_members").delete(record_id)

    def _unassign_task(self, record_id: RecordId, row: Tuple) -> None:
        task = self._validated_task(row)
        updated = Task(
            task.id, task.project_id, task.title, task.description, task.status,
            task.priority, None, task.created_by_user_id, task.created_at,
            self._later_than(task.updated_at), task.due_date,
        )
        self._table("tasks").update(record_id, Tuple((
            updated.id, updated.project_id, updated.title, updated.description,
            updated.status, updated.priority, updated.assignee_user_id,
            updated.created_by_user_id, updated.created_at, updated.updated_at,
        ), schema=row.schema))

    def _due_date_for_task(self, task_id: int) -> str | None:
        records = self._indexed_records("task_due_dates", "task_id", task_id)
        if len(records) > 1:
            raise ProductValidationError(f"Task {task_id} has duplicate due-date records.")
        if not records:
            return None
        return self._validated_due_date(records[0][1][1])

    def _set_due_date(self, task_id: int, value: str | None) -> None:
        value = self._validated_due_date(value)
        records = self._indexed_records("task_due_dates", "task_id", task_id)
        if len(records) > 1:
            raise ProductValidationError(f"Task {task_id} has duplicate due-date records.")
        if records and value is None:
            self._table("task_due_dates").delete(records[0][0])
        elif records:
            self._table("task_due_dates").update(
                records[0][0], Tuple((task_id, value), schema=records[0][1].schema),
            )
        elif value is not None:
            self._table("task_due_dates").insert((task_id, value))

    @staticmethod
    def _validated_due_date(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ProductValidationError("due_date must be an ISO calendar date or null.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ProductValidationError("due_date must use YYYY-MM-DD and be a valid calendar date.") from None
        if parsed.isoformat() != value:
            raise ProductValidationError("due_date must use canonical YYYY-MM-DD format.")
        return value

    @staticmethod
    def _bounded_optional_text(name: str, value: str | None, maximum: int) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ProductValidationError(f"{name} must be a string or None.")
        if isinstance(value, str) and len(value) > maximum:
            raise ProductValidationError(f"{name} must not exceed {maximum} characters.")
        return value

    def _append_activity(
        self, task: Task, workspace_id: int, actor_user_id: int,
        event_type: str, details: dict[str, object] | None,
    ) -> RecordId:
        payload = None if details is None else json.dumps(details, sort_keys=True, separators=(",", ":"))
        if payload is not None and len(payload) > 2048:
            raise ProductValidationError("Activity details exceed the storage limit.")
        event = TaskActivity(
            self._next_id("task_activity"), task.id, task.project_id, workspace_id,
            actor_user_id, event_type, payload, self._now(),
        )
        return self._table("task_activity").insert((
            event.id, event.task_id, event.project_id, event.workspace_id,
            event.actor_user_id, event.event_type, event.details, event.created_at,
        ))

    def _create_notification(
        self, recipient_user_id: int, actor_user_id: int | None,
        event_type: str, summary: str, workspace_id: int | None,
        project_id: int | None, task_id: int | None,
    ) -> RecordId | None:
        if actor_user_id == recipient_user_id:
            return None
        self._user_for_id(recipient_user_id)
        notification = Notification(
            self._next_id("notifications"), recipient_user_id, event_type, summary,
            workspace_id, project_id, task_id, self._now(), False, None,
        )
        return self._table("notifications").insert(self._notification_values(notification))

    def _safe_notification(self, item: Notification, actor_user_id: int) -> Notification | None:
        if item.recipient_user_id != actor_user_id:
            return None
        if item.workspace_id is not None and self._active_membership(item.workspace_id, actor_user_id) is None:
            return None
        if item.task_id is not None:
            try:
                task = self._task_for_id(item.task_id)
            except ProductNotFoundError:
                return Notification(
                    item.id, item.recipient_user_id, item.event_type, item.summary,
                    item.workspace_id, None, None, item.created_at, item.is_read, item.dismissed_at,
                )
            if item.workspace_id is None or self._project_for_id(task.project_id).workspace_id != item.workspace_id:
                return None
        return item

    def _filter_tasks(
        self, tasks: list[Task], *, query: str | None, status: str | None,
        priority: str | None, due_before: str | None, due_after: str | None,
    ) -> list[Task]:
        if query is not None:
            if not isinstance(query, str) or len(query) > 192:
                raise ProductValidationError("query must not exceed 192 characters.")
            needle = query.strip().casefold()
            if needle:
                tasks = [task for task in tasks if needle in task.title.casefold()]
        if status is not None:
            self._allowed("status", status, TASK_STATUSES)
            tasks = [task for task in tasks if task.status == status]
        if priority is not None:
            self._allowed("priority", priority, TASK_PRIORITIES)
            tasks = [task for task in tasks if task.priority == priority]
        before = self._validated_due_date(due_before)
        after = self._validated_due_date(due_after)
        if before is not None:
            tasks = [task for task in tasks if task.due_date is not None and task.due_date <= before]
        if after is not None:
            tasks = [task for task in tasks if task.due_date is not None and task.due_date >= after]
        return tasks

    @staticmethod
    def _sort_tasks(tasks: list[Task], sort: str) -> list[Task]:
        options: dict[str, tuple[Callable[[Task], object], bool]] = {
            "id": (lambda task: task.id, False),
            "updated_desc": (lambda task: (task.updated_at, task.id), True),
            "due_asc": (lambda task: (task.due_date is None, task.due_date or "", task.id), False),
            "due_desc": (lambda task: (task.due_date is not None, task.due_date or "", task.id), True),
            "title": (lambda task: (task.title.casefold(), task.id), False),
        }
        if sort not in options:
            raise ProductValidationError("sort must be one of: id, updated_desc, due_asc, due_desc, title.")
        key, reverse = options[sort]
        return sorted(tasks, key=key, reverse=reverse)

    @staticmethod
    def _limit(value: int, maximum: int) -> int:
        if type(value) is not int or value < 1 or value > maximum:
            raise ProductValidationError(f"limit must be between 1 and {maximum}.")
        return value

    @staticmethod
    def _offset(value: int) -> int:
        if type(value) is not int or value < 0:
            raise ProductValidationError("offset must be a non-negative integer.")
        return value

    @staticmethod
    def _task_values(task: Task) -> tuple[object, ...]:
        return (
            task.id, task.project_id, task.title, task.description, task.status,
            task.priority, task.assignee_user_id, task.created_by_user_id,
            task.created_at, task.updated_at,
        )

    @staticmethod
    def _notification_values(item: Notification) -> tuple[object, ...]:
        return (
            item.id, item.recipient_user_id, item.event_type, item.summary,
            item.workspace_id, item.project_id, item.task_id, item.created_at,
            item.is_read, item.dismissed_at,
        )

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

    def _validated_project(self, row: Tuple) -> Project:
        project = self._project(row)
        self._validate_project_creator(project)
        return project

    def _validated_task(self, row: Tuple) -> Task:
        task = self._task(row)
        self._project_for_id(task.project_id)
        self._user_for_id(task.created_by_user_id)
        return Task(
            task.id, task.project_id, task.title, task.description, task.status,
            task.priority, task.assignee_user_id, task.created_by_user_id,
            task.created_at, task.updated_at, self._due_date_for_task(task.id),
        )

    def _workspace_for_note(self, note: Note) -> Workspace:
        return self._workspace_for_id(self._project_for_id(self._task_for_id(note.task_id).project_id).workspace_id)

    def _require_self(self, user_id: int, actor_user_id: int | None) -> None:
        if actor_user_id is not None and actor_user_id != user_id:
            raise ProductNotFoundError("Resource does not exist.")

    def _active_membership(self, workspace_id: int, user_id: int) -> WorkspaceMember | None:
        try:
            user = self._user_for_id(user_id)
        except ProductNotFoundError:
            return None
        if user.account_state != "ACTIVE":
            return None
        return next((member for member in self._members_for_workspace(workspace_id) if member.user_id == user_id), None)

    def _require_visible(self, workspace_id: int, actor_user_id: int | None) -> WorkspaceMember | None:
        if actor_user_id is None:
            return None
        member = self._active_membership(workspace_id, actor_user_id)
        if member is None:
            raise ProductNotFoundError("Resource does not exist.")
        return member

    def _require_owner(self, workspace: Workspace, actor_user_id: int | None) -> None:
        member = self._require_visible(workspace.id, actor_user_id)
        if member is not None and member.role != "OWNER":
            raise ProductPermissionError("Workspace owner permission is required.")

    @staticmethod
    def _require_collaborative(workspace: Workspace) -> None:
        if workspace.kind == "PERSONAL":
            raise ProductPermissionError("Personal workspaces do not support membership changes.")

    def _require_creator_or_owner_fallback(self, workspace_id: int, creator_user_id: int, actor_user_id: int | None) -> None:
        member = self._require_visible(workspace_id, actor_user_id)
        if member is None:
            return
        if actor_user_id == creator_user_id:
            return
        if member.role == "OWNER" and self._active_membership(workspace_id, creator_user_id) is None:
            return
        raise ProductPermissionError("Only the creator may delete this resource.")

    def _require_note_author(self, note: Note, actor_user_id: int | None) -> None:
        if actor_user_id is None:
            return
        self._require_visible(self._workspace_for_note(note).id, actor_user_id)
        if note.author_user_id != actor_user_id:
            raise ProductPermissionError("Only the note author may modify this note.")

    def _require_membership(self, workspace_id: int, user_id: int, subject: str) -> None:
        if self._active_membership(workspace_id, user_id) is None:
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
    def _canonical_email(value: str) -> str:
        if not isinstance(value, str):
            raise ProductValidationError("email must be a string.")
        email = value.strip().casefold()
        if not email:
            raise ProductValidationError("email must not be empty.")
        if len(email) > 254:
            raise ProductValidationError("email must not exceed 254 characters.")
        if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) is None:
            raise ProductValidationError("Enter a valid email address.")
        return email

    @staticmethod
    def _registration_name(value: str) -> str:
        if not isinstance(value, str):
            raise ProductValidationError("name must be a string.")
        name = value.strip()
        if not name:
            raise ProductValidationError("name must not be empty.")
        if len(name) > 96:
            raise ProductValidationError("name must not exceed 96 characters.")
        return name

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
    def _activity(row: Tuple) -> TaskActivity:
        if row[6] is not None:
            try:
                details = json.loads(row[6])
            except (TypeError, json.JSONDecodeError):
                raise ProductValidationError("Invalid persisted task activity details.") from None
            if not isinstance(details, dict):
                raise ProductValidationError("Task activity details must be a JSON object.")
        return TaskActivity(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])

    @staticmethod
    def _notification(row: Tuple) -> Notification:
        return Notification(
            row[0], row[1], row[2], row[3], row[4], row[5], row[6],
            row[7], row[8], row[9],
        )

    @staticmethod
    def _note(row: Tuple) -> Note:
        return Note(row[0], row[1], row[2], row[3], row[4], row[5])

    @staticmethod
    def _session(row: Tuple) -> Session:
        digest = row[2]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ProductValidationError("Invalid persisted session token digest.")
        return Session(row[0], row[1], digest, row[3], row[4])
