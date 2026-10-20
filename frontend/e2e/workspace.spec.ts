import { createProjectThroughUI, createWorkspaceThroughUI, expect, registerThroughUI, test, uniqueAccount } from "./fixtures";

test("@workspace workspace switching, project navigation, sidebar, and command palette", async ({ page }) => {
  await registerThroughUI(page, uniqueAccount("Workspace"));
  const first = `Alpha ${Date.now()}`, second = `Beta ${Date.now()}`;
  await createWorkspaceThroughUI(page, first);
  await createProjectThroughUI(page, "Alpha project");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByLabel("New collaborative workspace").fill(second);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.locator("#workspace-selector option:checked")).toHaveText(second);
  await createProjectThroughUI(page, "Beta project");

  await page.locator("#workspace-selector").selectOption({ label: first });
  await expect(page.getByRole("heading", { name: "Alpha project" })).toBeVisible();
  await page.locator("#workspace-selector").selectOption({ label: second });
  await expect(page.getByRole("heading", { name: "Beta project" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Alpha project" })).not.toBeVisible();

  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await page.getByRole("combobox", { name: "Search commands" }).fill("Inbox");
  await expect(page.getByRole("option", { name: /Go to Inbox/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/inbox$/);
  await page.getByRole("link", { name: "Common Dashboard" }).first().click();
  await expect(page.getByRole("heading", { name: /Welcome,/ })).toBeVisible();
  await page.getByRole("button", { name: `Workspace: ${second}` }).click();
  await expect(page.getByRole("option", { name: new RegExp(first) })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("option", { name: new RegExp(first) })).toHaveCount(0);
});
