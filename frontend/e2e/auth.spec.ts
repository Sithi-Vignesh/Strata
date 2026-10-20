import { expect, loginThroughUI, registerThroughUI, test, uniqueAccount } from "./fixtures";

test.describe("@auth authentication", () => {
  test("registration, refresh persistence, logout, login, and invalid login", async ({ page }) => {
    const account = uniqueAccount("Auth");
    await registerThroughUI(page, account);
    await page.reload();
    await expect(page.getByText(account.email, { exact: true }).first()).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).first().click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/tasks");
    await expect(page).toHaveURL(/\/login$/);

    await page.getByLabel("Email").fill(account.email);
    await page.locator('input[name="password"]').fill("not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toContainText("Invalid email or password");
    await loginThroughUI(page, account);
  });

  test("two browser contexts retain independent session cookies", async ({ browser, baseURL }) => {
    const first = await browser.newContext({ baseURL }), second = await browser.newContext({ baseURL });
    const accountA = uniqueAccount("Session A"), accountB = uniqueAccount("Session B");
    try {
      const pageA = await first.newPage(), pageB = await second.newPage();
      await registerThroughUI(pageA, accountA);
      await registerThroughUI(pageB, accountB);
      await expect(pageA.getByText(accountA.email, { exact: true }).first()).toBeVisible();
      await expect(pageB.getByText(accountB.email, { exact: true }).first()).toBeVisible();
      const cookieA = (await first.cookies()).find((cookie) => cookie.name === "strata_session");
      const cookieB = (await second.cookies()).find((cookie) => cookie.name === "strata_session");
      expect(cookieA?.httpOnly).toBe(true);
      expect(cookieA?.sameSite).toBe("Lax");
      expect(cookieA?.value).not.toBe(cookieB?.value);
    } finally { await first.close(); await second.close(); }
  });
});
