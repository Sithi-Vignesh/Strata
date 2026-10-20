import { apiJson, createProjectThroughUI, createWorkspaceThroughUI, expect, registerThroughUI, test, uniqueAccount } from "./fixtures";

test("@security protected routes redirect and revocation removes browser and API access", async ({ browser, page, baseURL }) => {
  await page.goto("/tasks");
  await expect(page).toHaveURL(/\/login$/);

  const ownerContext = await browser.newContext({ baseURL }), memberContext = await browser.newContext({ baseURL });
  try {
    const ownerPage = await ownerContext.newPage(), memberPage = await memberContext.newPage();
    const owner = uniqueAccount("Security owner"), member = uniqueAccount("Security member");
    await registerThroughUI(ownerPage, owner); await registerThroughUI(memberPage, member);
    const workspace = `Secured ${Date.now()}`, project = `Private ${Date.now()}`;
    await createWorkspaceThroughUI(ownerPage, workspace); await createProjectThroughUI(ownerPage, project);
    const me = await apiJson<{ id: number }>(ownerContext.request, "get", "/api/auth/me");
    const workspaces = await apiJson<Array<{ id: number; name: string }>>(ownerContext.request, "get", `/api/users/${me.id}/workspaces`);
    const workspaceId = workspaces.find((item) => item.name === workspace)?.id;
    if (!workspaceId) throw new Error("Shared workspace was not found through the authenticated owner session.");
    const projects = await apiJson<Array<{ id: number; name: string }>>(ownerContext.request, "get", `/api/workspaces/${workspaceId}/projects`);
    const projectId = projects.find((item) => item.name === project)?.id;
    if (!projectId) throw new Error("Project was not found through the authenticated owner session.");
    const task = await apiJson<{ id: number }>(ownerContext.request, "post", `/api/projects/${projectId}/tasks`, { title: "Revocation task" }, 201);

    const beforeMembership = await memberContext.request.get(`/api/workspaces/${workspaceId}`);
    expect(beforeMembership.status()).toBe(404);
    await ownerPage.getByRole("link", { name: "Members" }).first().click();
    await ownerPage.getByRole("main").getByLabel("Member email").fill(member.email);
    await ownerPage.getByRole("main").getByRole("button", { name: "Add member" }).click();
    await expect(ownerPage.getByRole("status")).toContainText("Member added to the workspace");
    await memberPage.reload();
    await memberPage.locator("#workspace-selector").selectOption({ label: workspace });
    await memberPage.getByRole("link", { name: "Tasks", exact: true }).first().click();
    await expect(memberPage.getByRole("button", { name: "Revocation task" })).toBeVisible();

    await ownerPage.getByRole("link", { name: "Members" }).first().click();
    const memberRow = ownerPage.locator("article").filter({ hasText: member.email });
    await memberRow.getByRole("button", { name: "Remove" }).click();
    await ownerPage.getByRole("dialog", { name: new RegExp(`Remove ${member.name}`) }).getByRole("button", { name: "Remove member" }).click();
    await expect(ownerPage.getByRole("status")).toContainText("Member removed");

    expect((await memberContext.request.get(`/api/workspaces/${workspaceId}`)).status()).toBe(404);
    expect((await memberContext.request.get(`/api/tasks/${task.id}`)).status()).toBe(404);
    await memberPage.reload();
    await expect(memberPage.locator("#workspace-selector option", { hasText: workspace })).toHaveCount(0);
    await expect(memberPage.getByText("Revocation task")).toHaveCount(0);
  } finally { await ownerContext.close(); await memberContext.close(); }
});
