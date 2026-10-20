import { readFile, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { apiJson, createProjectThroughUI, createWorkspaceThroughUI, expect, loginThroughUI, openProjectTasks, registerThroughUI, test, uniqueAccount } from "./fixtures";

type Workspace = { id: number; name: string };
type Project = { id: number; name: string };
type Task = { id: number; title: string; status: string; assignee_user_id: number | null };
type User = { id: number; email: string };

test("@release complete two-user journey survives restart and enforces revocation", async ({ browser, baseURL }) => {
  const ownerContext = await browser.newContext({ baseURL });
  const memberContext = await browser.newContext({ baseURL });
  const owner = uniqueAccount("Release owner"), member = uniqueAccount("Release member");
  const token = Date.now();
  const workspaceName = `Release workspace ${token}`;
  const projectName = `Release project ${token}`;
  const originalTitle = `Release task ${token}`;
  const editedTitle = `${originalTitle} edited`;
  const handoff = "Please verify the release checklist and record the final outcome.";
  const note = "Validated in an independent collaborator browser session.";

  try {
    const ownerPage = await ownerContext.newPage(), memberPage = await memberContext.newPage();

    // Authentication: both registrations are real UI workflows and remain isolated.
    await registerThroughUI(ownerPage, owner);
    await ownerPage.reload();
    await expect(ownerPage.getByText(owner.email, { exact: true }).first()).toBeVisible();
    await registerThroughUI(memberPage, member);
    await memberPage.getByRole("button", { name: "Sign out" }).first().click();
    await expect(memberPage).toHaveURL(/\/login$/);
    await memberPage.getByLabel("Email").fill(member.email);
    await memberPage.locator('input[name="password"]').fill("invalid-release-password");
    await memberPage.getByRole("button", { name: "Sign in" }).click();
    await expect(memberPage.getByRole("alert")).toContainText("Invalid email or password");
    await loginThroughUI(memberPage, member);
    expect((await ownerContext.cookies()).find((item) => item.name === "strata_session")?.value)
      .not.toBe((await memberContext.cookies()).find((item) => item.name === "strata_session")?.value);

    // Workspace and membership: owner uses the UI, member sees access and owner-only controls stay hidden.
    await createWorkspaceThroughUI(ownerPage, workspaceName);
    await ownerPage.getByRole("link", { name: "Members" }).first().click();
    await ownerPage.getByRole("main").getByLabel("Member email").fill(member.email);
    await ownerPage.getByRole("main").getByRole("button", { name: "Add member" }).click();
    await expect(ownerPage.getByRole("status")).toContainText("Member added to the workspace");
    await memberPage.reload();
    await memberPage.locator("#workspace-selector").selectOption({ label: workspaceName });
    await memberPage.getByRole("link", { name: "Members" }).first().click();
    await expect(memberPage.getByText("Only the workspace owner can add or remove members.")).toBeVisible();
    await expect(memberPage.getByRole("button", { name: "Add member" })).toHaveCount(0);

    const ownerUser = await apiJson<User>(ownerContext.request, "get", "/api/auth/me");
    const memberUser = await apiJson<User>(memberContext.request, "get", "/api/auth/me");
    const ownerWorkspaces = await apiJson<Workspace[]>(ownerContext.request, "get", `/api/users/${ownerUser.id}/workspaces`);
    const shared = ownerWorkspaces.find((item) => item.name === workspaceName);
    const ownerPersonal = ownerWorkspaces.find((item) => item.name === "My Workspace");
    if (!shared || !ownerPersonal) throw new Error("Expected release workspaces were not found.");
    expect((await memberContext.request.get(`/api/workspaces/${ownerPersonal.id}`)).status()).toBe(404);
    expect((await memberContext.request.patch(`/api/workspaces/${shared.id}`, { data: { name: "Forbidden" } })).status()).toBe(403);

    // Project and task lifecycle: primary creation/edit/filter/board actions use Chromium.
    await ownerPage.locator("#workspace-selector").selectOption({ label: workspaceName });
    await createProjectThroughUI(ownerPage, projectName, "End-to-end release verification project");
    await openProjectTasks(ownerPage, projectName);
    await ownerPage.getByRole("button", { name: "New task" }).click();
    let dialog = ownerPage.getByRole("dialog", { name: "New task" });
    await dialog.getByLabel("Title").fill(originalTitle);
    await dialog.getByLabel("Description").fill("Created and maintained through the real product interface.");
    await dialog.getByLabel("Status").selectOption("TODO");
    await dialog.getByLabel("Priority").selectOption("HIGH");
    await dialog.getByLabel(/Due date/).fill("2030-06-15");
    await dialog.getByRole("button", { name: "Create task" }).click();
    let row = ownerPage.getByRole("row").filter({ hasText: originalTitle });
    await row.getByRole("button", { name: "Edit" }).click();
    dialog = ownerPage.getByRole("dialog", { name: "Edit task" });
    await dialog.getByLabel("Title").fill(editedTitle);
    await dialog.getByLabel("Assignee").selectOption({ label: member.name });
    await dialog.getByLabel("Handoff note").fill(handoff);
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await ownerPage.reload();
    row = ownerPage.getByRole("row").filter({ hasText: editedTitle });
    await expect(row).toContainText("High");
    await expect(row).toContainText("2030");
    await ownerPage.getByLabel("Search tasks").fill(`${token} edited`);
    await expect(ownerPage.getByText("1 results")).toBeVisible();
    await ownerPage.getByLabel("Status").selectOption("TODO");
    await ownerPage.getByLabel("Priority").selectOption("HIGH");
    await ownerPage.getByLabel("Sort").selectOption("title");
    await expect(row).toBeVisible();
    await ownerPage.getByRole("button", { name: "Clear filters" }).click();
    await ownerPage.goto("/board");
    await expect(ownerPage).toHaveURL(/\/board$/);
    await ownerPage.getByLabel(`Move ${editedTitle} to status`).selectOption("IN_PROGRESS");
    await expect(ownerPage.getByRole("region", { name: "In progress" }).getByText(editedTitle, { exact: true })).toBeVisible();

    // Collaboration and notifications in the second browser.
    await memberPage.goto("/my-tasks");
    await expect(memberPage.getByRole("heading", { name: "My Tasks" })).toBeVisible();
    await expect(memberPage.getByText(editedTitle, { exact: true })).toBeVisible();
    await memberPage.goto("/inbox");
    const unreadBadge = memberPage.getByLabel(/unread notifications/).first();
    await expect(unreadBadge).toBeVisible();
    const assignment = memberPage.locator("article").filter({ hasText: "A task was handed off to you." }).first();
    await expect(assignment).toBeVisible();
    await assignment.getByRole("button", { name: "Mark read" }).click();
    await expect(assignment.getByLabel("Read")).toBeVisible();
    await assignment.getByRole("button", { name: "Mark unread" }).click();
    await expect(assignment.getByLabel("Unread")).toBeVisible();
    await memberPage.getByRole("button", { name: "Mark all read" }).click();
    await expect(memberPage.getByLabel(/unread notifications/)).toHaveCount(0);
    const notificationRows = memberPage.locator("article.inbox-item");
    await expect.poll(() => notificationRows.count()).toBeGreaterThanOrEqual(2);
    const beforeDismiss = await notificationRows.count();
    const dismissTarget = notificationRows.filter({ hasNotText: "A task was handed off to you." }).first();
    await dismissTarget.getByRole("button", { name: "Dismiss" }).click();
    await expect(notificationRows).toHaveCount(beforeDismiss - 1);
    await assignment.getByRole("button", { name: /A task was handed off to you/ }).click();
    await expect(memberPage).toHaveURL(/\/tasks/);
    await expect(memberPage.getByRole("dialog", { name: editedTitle })).toBeVisible();
    await memberPage.getByLabel("New note").fill(note);
    await memberPage.getByRole("button", { name: "Add note" }).click();
    await expect(memberPage.getByText(note, { exact: true })).toBeVisible();
    await memberPage.getByRole("button", { name: "Edit task" }).click();
    dialog = memberPage.getByRole("dialog", { name: "Edit task" });
    await dialog.getByLabel("Status").selectOption("DONE");
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await ownerPage.goto("/tasks");
    await ownerPage.reload();
    row = ownerPage.getByRole("row").filter({ hasText: editedTitle });
    await expect(row).toContainText("Done");
    await row.getByRole("button", { name: editedTitle }).click();
    const detail = ownerPage.getByRole("dialog", { name: editedTitle });
    await expect(detail.getByText(note, { exact: true })).toBeVisible();
    await expect(detail.locator("blockquote")).toContainText(handoff);
    await expect(detail.getByText(member.name, { exact: false }).first()).toBeVisible();
    await ownerPage.getByRole("button", { name: "Close task detail" }).click();

    const projects = await apiJson<Project[]>(ownerContext.request, "get", `/api/workspaces/${shared.id}/projects`);
    const project = projects.find((item) => item.name === projectName);
    if (!project) throw new Error("Release project not found.");
    const tasks = await apiJson<Task[]>(ownerContext.request, "get", `/api/projects/${project.id}/tasks`);
    const task = tasks.find((item) => item.title === editedTitle);
    if (!task) throw new Error("Release task not found.");
    const activityBefore = await apiJson<{ items: Array<{ actor_user_id: number; event_type: string }>; total: number }>(ownerContext.request, "get", `/api/tasks/${task.id}/activity`);
    expect(activityBefore.items.some((item) => item.actor_user_id === ownerUser.id && item.event_type === "ASSIGNEE_CHANGED")).toBe(true);
    expect(activityBefore.items.some((item) => item.actor_user_id === memberUser.id && item.event_type === "TASK_COMPLETED")).toBe(true);

    // A real graceful backend stop/reopen uses the same disposable stores.
    await restartBackend();
    await ownerPage.reload();
    await memberPage.reload();
    await expect(ownerPage.getByText(owner.email, { exact: true }).first()).toBeVisible();
    await expect(memberPage.getByText(member.email, { exact: true }).first()).toBeVisible();
    await ownerPage.locator("#workspace-selector").selectOption({ label: workspaceName });
    await ownerPage.goto("/tasks");
    await expect(ownerPage.getByRole("row").filter({ hasText: editedTitle })).toContainText("Done");
    const persistedActivity = await apiJson<{ total: number }>(ownerContext.request, "get", `/api/tasks/${task.id}/activity`);
    expect(persistedActivity.total).toBe(activityBefore.total);

    // Revocation removes UI and API access, including stale member browser state.
    await ownerPage.getByRole("link", { name: "Members" }).first().click();
    const memberRow = ownerPage.locator("article").filter({ hasText: member.email });
    await memberRow.getByRole("button", { name: "Remove" }).click();
    await ownerPage.getByRole("dialog", { name: new RegExp(`Remove ${member.name}`) }).getByRole("button", { name: "Remove member" }).click();
    await expect(ownerPage.getByRole("status")).toContainText("Member removed");
    expect((await memberContext.request.get(`/api/tasks/${task.id}`)).status()).toBe(404);
    expect((await memberContext.request.patch(`/api/tasks/${task.id}`, { data: { status: "TODO" } })).status()).toBe(404);
    await memberPage.reload();
    await expect(memberPage.locator("#workspace-selector option", { hasText: workspaceName })).toHaveCount(0);
    await expect(memberPage.getByText(editedTitle)).toHaveCount(0);

    await ownerPage.getByRole("button", { name: "Sign out" }).first().click();
    await memberPage.getByRole("button", { name: "Sign out" }).first().click();
    await expect(ownerPage).toHaveURL(/\/login$/);
    await expect(memberPage).toHaveURL(/\/login$/);
    await ownerPage.goto("/tasks");
    await memberPage.goto("/tasks");
    await expect(ownerPage).toHaveURL(/\/login$/);
    await expect(memberPage).toHaveURL(/\/login$/);
  } finally {
    await ownerContext.close();
    await memberContext.close();
  }
});

async function restartBackend(): Promise<void> {
  const control = process.env.STRATA_E2E_CONTROL_DIR;
  if (!control) throw new Error("P1 E2E restart control is unavailable.");
  const nonce = `restart-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const requestPath = join(control, "restart-request.json");
  const responsePath = join(control, "restart-response.json");
  await unlink(responsePath).catch(() => undefined);
  await writeFile(requestPath, JSON.stringify({ nonce }), "utf8");
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    try {
      const response = JSON.parse(await readFile(responsePath, "utf8")) as { nonce?: string; status?: string; error?: string };
      if (response.nonce === nonce) {
        await unlink(responsePath).catch(() => undefined);
        if (response.status !== "ready") throw new Error(`Backend restart failed: ${response.error ?? "unknown error"}`);
        return;
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT" && error instanceof SyntaxError === false) throw error;
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error("Timed out waiting for the graceful E2E backend restart.");
}
