import { createProjectThroughUI, createWorkspaceThroughUI, expect, openProjectTasks, registerThroughUI, test, uniqueAccount } from "./fixtures";

test("@tasks complete task lifecycle persists through refresh", async ({ page }) => {
  await registerThroughUI(page, uniqueAccount("Tasks"));
  const workspace = `Task workspace ${Date.now()}`, project = `Delivery ${Date.now()}`, title = `Browser task ${Date.now()}`, edited = `${title} edited`;
  await createWorkspaceThroughUI(page, workspace);
  await createProjectThroughUI(page, project);
  await openProjectTasks(page, project);

  await page.getByRole("button", { name: "New task" }).click();
  const create = page.getByRole("dialog", { name: "New task" });
  await create.getByLabel("Title").fill(title);
  await create.getByLabel("Description").fill("Created through Chromium");
  await create.getByLabel("Status").selectOption("IN_PROGRESS");
  await create.getByLabel("Priority").selectOption("HIGH");
  await create.getByLabel(/Due date/).fill("2030-01-15");
  await create.getByRole("button", { name: "Create task" }).click();
  const row = page.getByRole("row").filter({ hasText: title });
  await expect(row).toContainText("In progress");
  await expect(row).toContainText("High");
  await expect(row).toContainText("2030");

  await row.getByRole("button", { name: "Edit" }).click();
  const edit = page.getByRole("dialog", { name: "Edit task" });
  await edit.getByLabel("Title").fill(edited);
  await edit.getByLabel("Status").selectOption("DONE");
  await edit.getByRole("button", { name: "Save changes" }).click();
  await page.reload();
  const persisted = page.getByRole("row").filter({ hasText: edited });
  await expect(persisted).toContainText("Done");
  await persisted.getByRole("button", { name: edited }).click();
  await expect(page.getByRole("dialog", { name: edited })).toContainText("Created through Chromium");
  await page.getByRole("button", { name: "Close task detail" }).click();
  await persisted.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: "Delete task?" }).getByRole("button", { name: "Delete task" }).click();
  await expect(page.getByRole("row").filter({ hasText: edited })).toHaveCount(0);
});
