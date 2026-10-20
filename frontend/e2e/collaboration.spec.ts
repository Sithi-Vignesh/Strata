import { apiJson, createProjectThroughUI, createWorkspaceThroughUI, expect, expectNotificationEvent, openProjectTasks, registerThroughUI, test, uniqueAccount, type Account } from "./fixtures";
import type { BrowserContext, Page } from "@playwright/test";

test("@collaboration two users share a task without cookie leakage", async ({ browser, baseURL }) => {
  const ownerContext = await browser.newContext({ baseURL }), memberContext = await browser.newContext({ baseURL });
  const owner = uniqueAccount("Owner"), member = uniqueAccount("Member");
  let ownerPage: Page, memberPage: Page;
  try {
    ownerPage = await ownerContext.newPage(); memberPage = await memberContext.newPage();
    await registerThroughUI(ownerPage, owner);
    await registerThroughUI(memberPage, member);
    const workspace = `Shared ${Date.now()}`, project = `Joint ${Date.now()}`, task = `Assigned ${Date.now()}`;
    await createWorkspaceThroughUI(ownerPage, workspace);
    await createProjectThroughUI(ownerPage, project);

    await ownerPage.getByRole("link", { name: "Members" }).first().click();
    await ownerPage.getByRole("main").getByLabel("Member email").fill(member.email);
    await ownerPage.getByRole("main").getByRole("button", { name: "Add member" }).click();
    await expect(ownerPage.getByRole("status")).toContainText("Member added to the workspace");

    await ownerPage.getByRole("link", { name: "Projects" }).first().click();
    await openProjectTasks(ownerPage, project);
    await ownerPage.getByRole("button", { name: "New task" }).click();
    const dialog = ownerPage.getByRole("dialog", { name: "New task" });
    await dialog.getByLabel("Title").fill(task);
    await dialog.getByLabel("Assignee").selectOption({ label: member.name });
    await dialog.getByRole("button", { name: "Create task" }).click();
    await expectNotificationEvent(memberContext.request, "TASK_ASSIGNED");

    await memberPage.reload();
    await memberPage.locator("#workspace-selector").selectOption({ label: workspace });
    await memberPage.getByRole("link", { name: "Tasks", exact: true }).first().click();
    const memberRow = memberPage.getByRole("row").filter({ hasText: task });
    await expect(memberRow).toContainText(member.name);
    await memberRow.getByRole("button", { name: "Edit" }).click();
    await memberPage.getByRole("dialog", { name: "Edit task" }).getByLabel("Status").selectOption("DONE");
    await memberPage.getByRole("button", { name: "Save changes" }).click();

    await ownerPage.reload();
    await expect(ownerPage.getByRole("row").filter({ hasText: task })).toContainText("Done");
    await assertDifferentSessions(ownerContext, memberContext, owner, member);
  } finally { await ownerContext.close(); await memberContext.close(); }
});

async function assertDifferentSessions(ownerContext: BrowserContext, memberContext: BrowserContext, owner: Account, member: Account) {
  const ownerMe = await apiJson<{ email: string }>(ownerContext.request, "get", "/api/auth/me");
  const memberMe = await apiJson<{ email: string }>(memberContext.request, "get", "/api/auth/me");
  expect(ownerMe.email).toBe(owner.email); expect(memberMe.email).toBe(member.email);
  const ownerCookie = (await ownerContext.cookies()).find((cookie) => cookie.name === "strata_session");
  const memberCookie = (await memberContext.cookies()).find((cookie) => cookie.name === "strata_session");
  expect(ownerCookie?.value).not.toBe(memberCookie?.value);
}
