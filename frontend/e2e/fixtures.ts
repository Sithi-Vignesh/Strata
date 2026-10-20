import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

export type Account = { name: string; email: string; password: string };
export const test = base;
export { expect };

export function uniqueAccount(prefix: string): Account {
  const token = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return { name: `${prefix} ${token.slice(-5)}`, email: `${prefix.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${token}@example.test`, password: `Strata-${token}-password` };
}

export async function registerThroughUI(page: Page, account: Account): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Name").fill(account.name);
  await page.getByLabel("Email").fill(account.email);
  await page.locator('input[name="password"]').fill(account.password);
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/"),
    page.getByRole("button", { name: "Create account" }).click(),
  ]);
  await expect(page.getByText(account.email, { exact: true }).first()).toBeVisible();
}

export async function loginThroughUI(page: Page, account: Account): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(account.email);
  await page.locator('input[name="password"]').fill(account.password);
  await Promise.all([
    page.waitForURL((url) => url.pathname === "/"),
    page.getByRole("button", { name: "Sign in" }).click(),
  ]);
  await expect(page.getByText(account.email, { exact: true }).first()).toBeVisible();
}

export async function createWorkspaceThroughUI(page: Page, name: string): Promise<void> {
  await page.getByRole("button", { name: "Create workspace" }).click();
  await page.getByLabel("New collaborative workspace").fill(name);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.locator("#workspace-selector")).toHaveValue(await optionValue(page, name));
}

export async function createProjectThroughUI(page: Page, name: string, description = "Browser acceptance project"): Promise<void> {
  await page.getByRole("link", { name: "Projects" }).first().click();
  await expect(page).toHaveURL(/\/projects$/);
  await page.getByLabel("Project name").fill(name);
  await page.getByLabel("Description").fill(description);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
}

export async function openProjectTasks(page: Page, projectName: string): Promise<void> {
  const tile = page.locator("article").filter({ has: page.getByRole("heading", { name: projectName, exact: true }) });
  await tile.getByRole("button", { name: "Open tasks" }).click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
}

export async function apiJson<T>(request: APIRequestContext, method: "get" | "post" | "patch" | "delete", path: string, data?: object, expected = 200): Promise<T> {
  const response = await request.fetch(path, { method: method.toUpperCase(), ...(data ? { data } : {}) });
  expect(response.status(), `${method.toUpperCase()} ${path}`).toBe(expected);
  return expected === 204 ? undefined as T : await response.json() as T;
}

export async function expectNotificationEvent(request: APIRequestContext, eventType: string): Promise<void> {
  await expect.poll(async () => {
    const notifications = await apiJson<{ items: Array<{ event_type: string }> }>(request, "get", "/api/notifications?unread_only=true&limit=20");
    return notifications.items.map((item) => item.event_type);
  }).toContain(eventType);
}

export async function expectNoDocumentOverflow(page: Page): Promise<void> {
  const sizes = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(sizes.scroll, `document width ${sizes.scroll}px exceeds viewport ${sizes.client}px`).toBeLessThanOrEqual(sizes.client + 1);
}

async function optionValue(page: Page, label: string): Promise<string> {
  return page.locator("#workspace-selector").locator("option", { hasText: label }).getAttribute("value").then((value) => {
    if (!value) throw new Error(`Workspace option '${label}' was not found.`);
    return value;
  });
}
