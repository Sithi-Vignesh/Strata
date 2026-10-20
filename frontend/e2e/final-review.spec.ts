import type { BrowserContext, Page } from "@playwright/test";
import { apiJson, expect, registerThroughUI, test, uniqueAccount } from "./fixtures";

type User = { id: number; name: string };
type Workspace = { id: number; name: string };
type Project = { id: number };
type Task = { id: number; title: string };

test("@release final workspace scopes and reused-id activity remain isolated", async ({ browser, baseURL }) => {
  const ownerContext = await browser.newContext({ baseURL }), memberContext = await browser.newContext({ baseURL });
  let ownerPage: Page, memberPage: Page;
  try {
    ownerPage = await ownerContext.newPage(); memberPage = await memberContext.newPage();
    const ownerAccount = uniqueAccount("Final Owner"), memberAccount = uniqueAccount("Final Member");
    await registerThroughUI(ownerPage, ownerAccount); await registerThroughUI(memberPage, memberAccount);
    const owner = await apiJson<User>(ownerContext.request, "get", "/api/auth/me");
    const member = await apiJson<User>(memberContext.request, "get", "/api/auth/me");
    const token = Date.now(), alphaName = `Final Alpha ${token}`, betaName = `Final Beta ${token}`;
    const alpha = await apiJson<Workspace>(ownerContext.request, "post", "/api/workspaces", { name: alphaName }, 201);
    const beta = await apiJson<Workspace>(ownerContext.request, "post", "/api/workspaces", { name: betaName }, 201);
    for (const workspace of [alpha, beta]) await apiJson(ownerContext.request, "post", `/api/workspaces/${workspace.id}/members`, { email: memberAccount.email }, 201);
    const alphaProject = await apiJson<Project>(ownerContext.request, "post", `/api/workspaces/${alpha.id}/projects`, { name: "Alpha delivery" }, 201);
    const betaProject = await apiJson<Project>(ownerContext.request, "post", `/api/workspaces/${beta.id}/projects`, { name: "Beta delivery" }, 201);

    const deleted = await apiJson<Task>(ownerContext.request, "post", `/api/projects/${betaProject.id}/tasks`, { title: "Deleted predecessor" }, 201);
    await apiJson(ownerContext.request, "delete", `/api/tasks/${deleted.id}`, undefined, 204);
    const activityTask = await apiJson<Task>(ownerContext.request, "post", `/api/projects/${alphaProject.id}/tasks`, { title: "Manual Collaboration test", assignee_user_id: owner.id }, 201);
    expect(activityTask.id).toBeGreaterThan(deleted.id);
    await apiJson(ownerContext.request, "patch", `/api/tasks/${activityTask.id}`, { assignee_user_id: member.id, handoff_note: "Continue the browser regression." });
    const alphaTask = await apiJson<Task>(ownerContext.request, "post", `/api/projects/${alphaProject.id}/tasks`, { title: "Alpha assigned", assignee_user_id: member.id }, 201);
    const betaTask = await apiJson<Task>(ownerContext.request, "post", `/api/projects/${betaProject.id}/tasks`, { title: "Beta assigned", assignee_user_id: member.id }, 201);

    await memberPage.reload();
    await memberPage.locator("#workspace-selector").selectOption({ label: alphaName });
    await memberPage.goto("/my-tasks");
    await expect(memberPage.getByText(alphaTask.title, { exact: true })).toBeVisible();
    await expect(memberPage.getByText(betaTask.title, { exact: true })).toHaveCount(0);
    await memberPage.locator("#workspace-selector").selectOption({ label: betaName });
    await expect(memberPage.getByText(betaTask.title, { exact: true })).toBeVisible();
    await expect(memberPage.getByText(alphaTask.title, { exact: true })).toHaveCount(0);

    await memberPage.goto("/all-tasks");
    await expect(memberPage.getByText(alphaTask.title, { exact: true })).toBeVisible();
    await expect(memberPage.getByText(betaTask.title, { exact: true })).toBeVisible();
    await memberPage.goto("/");
    await expect(memberPage.locator(".metric-card").filter({ hasText: "Workspaces" })).toBeVisible();
    await memberPage.goto("/workspace");
    await expect(memberPage.getByRole("heading", { name: betaName })).toBeVisible();

    await ownerPage.reload();
    await ownerPage.locator("#workspace-selector").selectOption({ label: alphaName });
    await ownerPage.goto(`/tasks?task=${activityTask.id}`);
    const detail = ownerPage.getByRole("dialog", { name: activityTask.title });
    await expect(detail.getByText(/Task created/i)).toBeVisible();
    await expect(detail.getByText(/Assignee changed/i)).toBeVisible();
    await expect(detail).toContainText("Continue the browser regression.");
    await expect(detail.getByRole("alert")).toHaveCount(0);

    await apiJson(ownerContext.request, "delete", `/api/workspaces/${beta.id}/members/${member.id}`, undefined, 204);
    await memberPage.goto("/all-tasks"); await memberPage.reload();
    await expect(memberPage.getByText(betaTask.title, { exact: true })).toHaveCount(0);
    await expect(memberPage.getByText(alphaTask.title, { exact: true })).toBeVisible();
  } finally { await ownerContext.close(); await memberContext.close(); }
});
