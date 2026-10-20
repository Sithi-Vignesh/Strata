# Frontend redesign notes

The Strata frontend uses a semantic token layer in `frontend/src/index.css` and a persistent `light`, `dark`, or `system` preference managed by `ThemeContext`. The authenticated shell keeps the existing authentication and product contexts intact; workspace and project changes continue to invalidate in-flight product data through the existing request-generation checks.

## Current navigation and task scope

- Responsive application shell with desktop sidebar, mobile overlay, contextual breadcrumbs, and compact mobile navigation.
- Global navigation for **Common Dashboard**, **All Tasks**, and **Inbox** across every workspace currently accessible to the signed-in user.
- Workspace navigation for **Workspace Dashboard**, **My Tasks**, **Projects**, **Tasks**, **Board**, and **Members**.
- **My Tasks** is scoped to the selected workspace and uses the server-side assigned-task endpoint with filtering, sorting, and pagination. It is no longer assembled client-side from project task lists.
- **All Tasks** uses the server-side accessible-task endpoint and preserves workspace/project identity for cross-workspace results.
- **Common Dashboard** reports membership-filtered, cross-workspace metrics; **Workspace Dashboard** reports the selected workspace only.
- Dedicated workspace **Members** experience for the existing add-by-email, removal, and ownership-transfer APIs.
- Persistent appearance settings and a quick theme toggle.
- Server-backed task search, status/priority/due-date filters, sorting, and pagination where applicable.
- Task due dates, deadline summaries, persistent notifications in **Inbox**, and task activity/history in the task detail drawer.
- Right-side task detail presentation while preserving notes, activity, and task mutation behavior.

Workspace changes clear workspace-scoped collections and retain request-generation guards so late responses cannot render data under a newly selected workspace. Inbox remains global. Opening a task from a global view revalidates access while selecting its workspace and loading its detail.

## Historical design decisions retained

The redesign began as a frontend-focused shell over the earlier product APIs. The semantic token system, responsive navigation, theme preference, request-generation protection, member-management flow, and detail-drawer approach remain in the current design. Later backend work added server-scoped task listings, dashboards, due-date state, notifications, and activity without discarding those foundations.

## Deliberately deferred

- Kanban drag-and-drop is not enabled because the backend has no ordering model. Accessible status controls remain the supported move interaction.
- Cross-workspace assignment discovery belongs in global **All Tasks**; **My Tasks** intentionally remains selected-workspace scoped.
- Calendar, project-health forecasting, billing, integrations, SSO, password reset, and invitation workflows remain outside the current product scope.
- Live multi-user updates remain refresh-based; no WebSocket or push channel was added.

The earlier redesign pass could not capture automated viewport screenshots. That historical limitation was later superseded by the P4 Playwright matrix, which exercises the current navigation, dashboards, task scopes, Inbox, task detail, and required responsive viewports. See [browser-testing.md](browser-testing.md) and [verification.md](verification.md) for current evidence.
