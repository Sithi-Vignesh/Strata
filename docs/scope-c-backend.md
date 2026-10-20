# Scope C backend expansion

## Data model and compatibility

Scope C is an additive extension. The legacy `tasks` schema is unchanged because Strata has no `ALTER TABLE` and persisted tuples carry a schema fingerprint. Changing that schema would make existing rows unreadable. Repeatable product bootstrap instead creates three missing sidecar tables and their indexes:

| Table | Purpose | Retention |
| --- | --- | --- |
| `task_due_dates` | Optional canonical `YYYY-MM-DD` value keyed by task ID | Deleted with the task |
| `task_activity` | Append-only logical task events with task/project/workspace/actor identity | Retained after task and project deletion; deleted with the workspace |
| `notifications` | Persistent pull notifications, read state, and dismissal timestamp | Hidden after access revocation; workspace-scoped rows deleted with the workspace |

Bootstrap creates missing tables and indexes without rewriting, resetting, or reseeding a non-empty database. Existing tasks read with `due_date: null`. Date-only values use ISO calendar semantics and have no timezone conversion.

## HTTP contracts

All routes require the existing session cookie and derive actor/recipient identity from it.

- `GET /api/my/tasks`: assigned tasks across currently accessible workspaces. Supports `query`, `status`, `priority`, `due_before`, `due_after`, `workspace_id`, `project_id`, `sort`, `limit`, and `offset`. The response contains `items`, `total`, `limit`, and `offset`; each item includes project and workspace identity. Maximum limit is 100.
- `GET /api/projects/{project_id}/tasks`: preserves the existing array response and adds the same text/domain/date filters, sorting, and bounded pagination. Maximum limit is 200.
- Task create and patch accept nullable `due_date`. Task patch also accepts an optional `handoff_note` of at most 1,000 characters, only when the assignee actually changes.
- `GET /api/tasks/{task_id}/activity`: newest-first activity page, maximum 100. Activity for a deleted task remains readable by current workspace members until workspace deletion.
- `GET /api/notifications`: newest-first notification page, with `unread_only`, `limit`, and `offset`; maximum 100.
- `GET /api/notifications/unread-count`: accessible unread count.
- `PATCH /api/notifications/{id}` with `{ "is_read": true|false }`: mark read or unread.
- `POST /api/notifications/mark-all-read`: mark all accessible, non-dismissed notifications read.
- `DELETE /api/notifications/{id}`: logical dismissal/archive.

Supported task orderings are `id`, `updated_desc`, `due_asc`, `due_desc`, and `title`. Pagination is deterministic within one serialized operation; it is offset-based rather than a snapshot cursor, so writes between separate page requests can shift later pages.

## Activity, handoffs, and notifications

Task creation and meaningful changes append explicit events. Status changes use `TASK_COMPLETED` and `TASK_REOPENED` where applicable; other event types cover title, description, status, priority, assignee, and due date changes. Details are bounded JSON containing only the changed field, old/new values, and an optional handoff note. Passwords, cookies, tokens, headers, and request bodies are never copied into events.

Task assignment/reassignment, handoff, assignee-relevant task changes, and membership changes produce persistent notifications. The actor is not notified about their own action. Notification summaries deliberately omit task titles and handoff content. Listing and mutation enforce recipient identity. Workspace-scoped notifications disappear from all recipient APIs immediately after membership revocation; a generic removal notification carries no workspace/project/task identifier. A deleted task is sanitized out of any still-visible notification link.

## Authorization and lifecycle

`/api/my/tasks` never accepts a user ID. It starts from the authenticated user's active memberships and intersects assigned-task rows with projects in those workspaces. Project task filters retain ordinary workspace authorization. Activity authorization uses the event's retained workspace identity, including after task deletion. Notification IDs return 404 to another recipient or after access is revoked.

Task deletion removes notes and due-date state, appends `TASK_DELETED`, and retains activity. Project deletion remains blocked while live tasks exist. Workspace deletion remains blocked while projects exist and removes memberships, retained activity, and workspace-scoped notifications before deleting the workspace. Member removal clears their assignments, immediately hides workspace-scoped notifications/history/tasks, and emits a context-free removal notification.

## Consistency and concurrency

Every operation uses the engine-owned reentrant database lock across authorization, reads, ID allocation, task mutation, activity append, notification creation, and index maintenance. Supported application paths therefore prevent deadlock cycles by coarse serialization. This is deadlock prevention, not deadlock detection, 2PL, MVCC, or multiprocess synchronization.

The engine has no general transaction manager or WAL. Scope C compound writes use ordered writes plus reverse compensation. An API success means every requested task/event/notification write completed. An in-process failure attempts to restore the base row and sidecar state and removes later event/notification writes. If an inverse write also fails, an explicit compensation error is raised. Power loss between writes, arbitrary crash recovery, and persistent I/O failure remain unsupported; the implementation does not claim atomic task-plus-event commits under those failures.

## Verification

Focused coverage is in `tests/test_scope_c_backend.py`: API authentication/authorization, cross-workspace isolation, valid/invalid dates, filtering/pagination, handoffs, activity, notification ownership/read/dismissal, revocation, normal restart, legacy database extension, injected event-write failure compensation, lifecycle retention/deletion, and bounded concurrent edits.

Run from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests\test_scope_c_backend.py -q
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run typecheck
npm run build
~~~

The supported deployment remains one backend worker/process and local filesystem storage.

### Final results (18 October 2026)

| Check | Result |
| --- | --- |
| Scope C focused tests | 8 passed |
| Full backend suite | 765 passed, 7 existing deprecation warnings |
| Frontend non-regression | 77 passed; TypeScript and production build passed |
| Live uvicorn HTTP/restart smoke | Passed, including Scope C due date, My Tasks, activity, notifications, restart, concurrency, and index validation |
| Diff validation | Passed; line-ending conversion notices only |
