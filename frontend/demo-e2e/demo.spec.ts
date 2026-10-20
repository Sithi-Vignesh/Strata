import { expect, test } from "@playwright/test";
import { loginThroughUI } from "../e2e/fixtures";

const owner = {
  name: "Demo Owner",
  email: "owner@demo.strata.local",
  password: "Strata-Demo-Owner-2026!",
};
const collaborator = {
  name: "Demo Collaborator",
  email: "collaborator@demo.strata.local",
  password: "Strata-Demo-Collaborator-2026!",
};

test("persistent demo supports independent owner and collaborator walkthroughs", async ({ browser, baseURL }) => {
  const ownerContext = await browser.newContext({ baseURL });
  const collaboratorContext = await browser.newContext({ baseURL });
  try {
    const ownerPage = await ownerContext.newPage();
    const collaboratorPage = await collaboratorContext.newPage();
    await loginThroughUI(ownerPage, owner);
    await loginThroughUI(collaboratorPage, collaborator);

    await ownerPage.locator("#workspace-selector").selectOption({ label: "Atlas Product Team" });
    await collaboratorPage.locator("#workspace-selector").selectOption({ label: "Atlas Product Team" });

    await ownerPage.goto("/tasks");
    await expect(ownerPage.getByText("Publish responsive landing page", { exact: true })).toBeVisible();

    await collaboratorPage.goto("/my-tasks");
    await expect(collaboratorPage.getByRole("heading", { name: "My Tasks" })).toBeVisible();
    await expect(collaboratorPage.getByText("Publish responsive landing page", { exact: true })).toBeVisible();
    await collaboratorPage.goto("/inbox");
    await expect(collaboratorPage.getByRole("heading", { name: "Inbox" })).toBeVisible();
    await expect(collaboratorPage.getByText(/assigned to you/i).first()).toBeVisible();

    const ownerCookie = (await ownerContext.cookies()).find((item) => item.name === "strata_session");
    const collaboratorCookie = (await collaboratorContext.cookies()).find((item) => item.name === "strata_session");
    expect(ownerCookie?.value).toBeTruthy();
    expect(collaboratorCookie?.value).toBeTruthy();
    expect(ownerCookie?.value).not.toBe(collaboratorCookie?.value);
  } finally {
    await ownerContext.close();
    await collaboratorContext.close();
  }
});
