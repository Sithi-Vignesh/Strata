import { apiJson, createProjectThroughUI, createWorkspaceThroughUI, expect, openProjectTasks, registerThroughUI, test, uniqueAccount } from "./fixtures";

test("@extended ownership transfer, workspace-scoped My Tasks, global All Tasks, project deletion, and rapid switching", async ({ browser, baseURL }) => {
  const firstContext = await browser.newContext({ baseURL }), secondContext = await browser.newContext({ baseURL });
  try {
    const firstPage = await firstContext.newPage(), secondPage = await secondContext.newPage();
    const first = uniqueAccount("Transfer first"), second = uniqueAccount("Transfer second"), token = Date.now();
    const shared = `Transfer ${token}`, other = `Other ${token}`, emptyProject = `Delete me ${token}`;
    await registerThroughUI(firstPage, first); await registerThroughUI(secondPage, second);
    await createWorkspaceThroughUI(firstPage, shared);
    await firstPage.getByRole("link", { name: "Members" }).first().click();
    await firstPage.getByRole("main").getByLabel("Member email").fill(second.email);
    await firstPage.getByRole("main").getByRole("button", { name: "Add member" }).click();
    await expect(firstPage.getByRole("status")).toContainText("Member added");
    await createProjectThroughUI(firstPage, emptyProject);

    await firstPage.getByRole("link", { name: "Members" }).first().click();
    const memberRow = firstPage.locator("article").filter({ hasText: second.email });
    await memberRow.getByRole("button", { name: "Make owner" }).click();
    await expect(firstPage.getByRole("status")).toContainText(`Ownership transferred to ${second.name}`);
    await expect(firstPage.getByText("Only the workspace owner can add or remove members.")).toBeVisible();
    await secondPage.reload();
    await secondPage.locator("#workspace-selector").selectOption({ label: shared });
    await secondPage.getByRole("link", { name: "Members" }).first().click();
    await expect(secondPage.locator("article").filter({ hasText: second.email })).toContainText("OWNER");

    await firstPage.getByRole("link", { name: "Projects" }).first().click();
    firstPage.once("dialog", (dialog) => dialog.accept());
    await firstPage.locator("article").filter({ hasText: emptyProject }).getByRole("button", { name: "Delete project" }).click();
    await expect(firstPage.getByRole("heading", { name: emptyProject })).toHaveCount(0);

    await createWorkspaceThroughUI(secondPage, other);
    await createProjectThroughUI(secondPage, `Other project ${token}`);
    await openProjectTasks(secondPage, `Other project ${token}`);
    await secondPage.getByRole("button", { name: "New task" }).click();
    let dialog = secondPage.getByRole("dialog", { name: "New task" });
    await dialog.getByLabel("Title").fill(`Other assignment ${token}`);
    await dialog.getByLabel("Assignee").selectOption({ label: second.name });
    await dialog.getByRole("button", { name: "Create task" }).click();
    await secondPage.locator("#workspace-selector").selectOption({ label: shared });
    await createProjectThroughUI(secondPage, `Shared project ${token}`);
    await openProjectTasks(secondPage, `Shared project ${token}`);
    await secondPage.getByRole("button", { name: "New task" }).click();
    dialog = secondPage.getByRole("dialog", { name: "New task" });
    await dialog.getByLabel("Title").fill(`Shared assignment ${token}`);
    await dialog.getByLabel("Assignee").selectOption({ label: second.name });
    await dialog.getByRole("button", { name: "Create task" }).click();
    await secondPage.goto("/my-tasks");
    await expect(secondPage.getByText(`Other assignment ${token}`, { exact: true })).toHaveCount(0);
    await expect(secondPage.getByText(`Shared assignment ${token}`, { exact: true })).toBeVisible();
    await secondPage.goto("/all-tasks");
    await expect(secondPage.getByText(`Other assignment ${token}`, { exact: true })).toBeVisible();
    await expect(secondPage.getByText(`Shared assignment ${token}`, { exact: true })).toBeVisible();

    for (let index = 0; index < 3; index += 1) {
      await secondPage.locator("#workspace-selector").selectOption({ label: other });
      await expect(secondPage.locator("#workspace-selector option:checked")).toHaveText(other);
      await secondPage.locator("#workspace-selector").selectOption({ label: shared });
      await expect(secondPage.locator("#workspace-selector option:checked")).toHaveText(shared);
    }
  } finally { await firstContext.close(); await secondContext.close(); }
});

test("@extended activity and notification pagination render server-backed next pages", async ({ browser, baseURL }) => {
  const ownerContext = await browser.newContext({ baseURL }), memberContext = await browser.newContext({ baseURL });
  try {
    const ownerPage = await ownerContext.newPage(), memberPage = await memberContext.newPage();
    const owner = uniqueAccount("Page owner"), member = uniqueAccount("Page member"), token = Date.now();
    await registerThroughUI(ownerPage, owner); await registerThroughUI(memberPage, member);
    const ownerUser = await apiJson<{ id: number }>(ownerContext.request, "get", "/api/auth/me");
    const memberUser = await apiJson<{ id: number }>(memberContext.request, "get", "/api/auth/me");
    const workspace = await apiJson<{ id: number }>(ownerContext.request, "post", "/api/workspaces", { name: `Pagination ${token}` }, 201);
    await apiJson(ownerContext.request, "post", `/api/workspaces/${workspace.id}/members`, { email: member.email }, 201);
    const project = await apiJson<{ id: number }>(ownerContext.request, "post", `/api/workspaces/${workspace.id}/projects`, { name: `Pagination project ${token}`, description: null }, 201);
    const activityTask = await apiJson<{ id: number }>(ownerContext.request, "post", `/api/projects/${project.id}/tasks`, { title: `Activity ${token}` }, 201);
    for (let index = 0; index < 22; index += 1) {
      await apiJson(ownerContext.request, "patch", `/api/tasks/${activityTask.id}`, { status: index % 2 === 0 ? "IN_PROGRESS" : "TODO" });
    }
    for (let index = 0; index < 21; index += 1) {
      await apiJson(ownerContext.request, "post", `/api/projects/${project.id}/tasks`, { title: `Notification ${token}-${index}`, assignee_user_id: memberUser.id }, 201);
    }

    await ownerPage.reload();
    await ownerPage.locator("#workspace-selector").selectOption({ label: `Pagination ${token}` });
    await ownerPage.getByRole("link", { name: "Projects" }).first().click();
    await openProjectTasks(ownerPage, `Pagination project ${token}`);
    await ownerPage.getByRole("button", { name: `Activity ${token}` }).click();
    const detail = ownerPage.getByRole("dialog", { name: `Activity ${token}` });
    await expect(detail.getByRole("button", { name: "Load older activity" })).toBeVisible();
    await detail.getByRole("button", { name: "Load older activity" }).click();
    await expect(detail.locator("article.activity-item")).toHaveCount(23);

    await memberPage.goto("/inbox");
    await expect(memberPage.getByRole("button", { name: "Load more" })).toBeVisible();
    await memberPage.getByRole("button", { name: "Load more" }).click();
    await expect(memberPage.locator("article.inbox-item")).toHaveCount(22);
    expect(ownerUser.id).not.toBe(memberUser.id);
  } finally { await ownerContext.close(); await memberContext.close(); }
});

test("@extended theme persistence, responsive navigation, accessible drawer, and pending logout", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await registerThroughUI(page, uniqueAccount("Theme"));
  const user = await apiJson<{ id: number }>(page.request, "get", "/api/auth/me");
  const workspaces = await apiJson<Array<{ id: number }>>(page.request, "get", `/api/users/${user.id}/workspaces`);
  const projects = await apiJson<Array<{ id: number }>>(page.request, "get", `/api/workspaces/${workspaces[0].id}/projects`);
  await apiJson(page.request, "post", `/api/projects/${projects[0].id}/tasks`, { title: "Accessible drawer task" }, 201);
  await page.reload();
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();

  await page.getByLabel(/Switch to dark theme/).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.evaluate(() => localStorage.setItem("strata.theme", "system"));
  await page.emulateMedia({ colorScheme: "light" });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.goto("/tasks");
  await page.getByRole("button", { name: "Accessible drawer task" }).click();
  const drawer = page.getByRole("dialog", { name: "Accessible drawer task" });
  await expect(drawer).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);

  await page.route("**/api/auth/logout", async (route) => {
    await new Promise((resolveWait) => setTimeout(resolveWait, 300));
    await route.continue();
  });
  const signOut = page.getByRole("banner").getByRole("button", { name: "Sign out" });
  await signOut.click();
  await expect(signOut).toBeDisabled();
  await expect(page).toHaveURL(/\/login$/);
});
