# Manual review stabilization

## Activity-history root cause and compatibility

Task deletion intentionally retains audit history, but the former task allocator chose `max(tasks.id) + 1` from live rows only. Deleting the highest task therefore allowed its ID to be reused. If the replacement belonged to another project or workspace, `/api/tasks/{id}/activity` found both generations and correctly rejected their mixed workspace identities with HTTP 422.

New task IDs are allocated above both live task IDs and retained `task_activity.task_id` values. Existing reused IDs are handled without deleting or rewriting history: the service exposes only the current generation when there is exactly one matching `TASK_CREATED` boundary, all mismatched events are older, and the older generation contains `TASK_DELETED`. Any ambiguous identity remains a 422 validation error. Authorization is derived from the current task before history is returned. Deleted-task history remains available while its workspace exists.

## UI fixes

- UI-01: the native visible selector was replaced by a themed, responsive listbox-style popover with full-name tooltips, focus treatment, arrow-key navigation, Escape and outside-click dismissal. A visually hidden native select remains only as a backwards-compatible automation surface.
- UI-02: task filters use a deliberate six-column desktop grid, balanced two-row intermediate layout, and one/two-column mobile layouts.
- UI-03: avatars now use deterministic first/last initials, Unicode-aware character selection, fixed line height, clipping, and centered flex alignment.
- UI-04: Kanban cards have a stronger title/description/due-date/metadata/action hierarchy, larger spacing, and clearer focus/hover states.
- UI-05: Kanban columns use content-driven minimum height, intentional empty drop targets, compact headers/counts, and no sticky-header strip.

## Scope architecture

Global navigation contains Common Dashboard, All Tasks, and Inbox. Workspace navigation contains Workspace Dashboard, My Tasks, Projects, Tasks, Board, and Members. Database and Settings remain separate.

- `GET /api/dashboard` aggregates only active memberships.
- `GET /api/workspaces/{workspace_id}/dashboard` requires current membership and returns only that workspace.
- `GET /api/tasks` provides authorized account-wide search, filters, deterministic sorting, and pagination, including workspace/project/assignee metadata.
- `GET /api/my/tasks` now requires `workspace_id`; the server validates membership and returns only that user's assignments in that workspace.

Workspace changes clear old frontend collections immediately and retain request-version guards, preventing stale results from being rendered under a new selection. Inbox remains global. Opening a global task revalidates access while loading its workspace and task detail.

## Compatibility and tests

No storage schema or existing row was changed. P1-P4 entry points remain supported. Regression coverage includes live and legacy activity generations, ambiguous corruption, restart persistence, multiple workspaces, global/workspace dashboards, server pagination/filtering, membership revocation, stale request protection, browser activity rendering, and four required responsive viewport sizes.

Known limitation: historical rows that lack an unambiguous retained deletion/current creation boundary are deliberately not auto-repaired; they continue to return a validation error for operator investigation.
