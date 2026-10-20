import { apiJson, expect, expectNoDocumentOverflow, registerThroughUI, test, uniqueAccount } from "./fixtures";

const viewports = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "desktop-1024", width: 1024, height: 768 },
  { name: "tablet-768", width: 768, height: 1024 },
  { name: "mobile-390", width: 390, height: 844 },
];

for (const viewport of viewports) {
  test(`@responsive ${viewport.name} keeps key screens reachable`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    await expectNoDocumentOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-login.png`), fullPage: true });

    await registerThroughUI(page, uniqueAccount(`Responsive ${viewport.name}`));
    const me = await apiJson<{ id: number }>(page.request, "get", "/api/auth/me");
    const workspaces = await apiJson<Array<{ id: number }>>(page.request, "get", `/api/users/${me.id}/workspaces`);
    const projects = await apiJson<Array<{ id: number }>>(page.request, "get", `/api/workspaces/${workspaces[0].id}/projects`);
    await apiJson(page.request, "post", `/api/projects/${projects[0].id}/tasks`, { title: `Responsive task ${viewport.name}`, due_date: "2030-06-15" }, 201);
    await page.reload();

    const routes = [
      { path: "/", heading: /Welcome,/, name: "common-dashboard" },
      { path: "/workspace", heading: "My Workspace", name: "workspace-dashboard" },
      { path: "/all-tasks", heading: "All Tasks", name: "all-tasks" },
      { path: "/my-tasks", heading: "My Tasks", name: "my-tasks" },
      { path: "/projects", heading: "Projects", name: "projects" },
      { path: "/tasks", heading: "Tasks", name: "tasks" },
      { path: "/board", heading: "Board", name: "board" },
      { path: "/inbox", heading: "Inbox", name: "inbox" },
    ];
    for (const route of routes) {
      await page.goto(route.path);
      await expect(page.getByRole("heading", { name: route.heading }).first()).toBeVisible();
      await expectNoDocumentOverflow(page);
      await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-${route.name}.png`), fullPage: true });
    }

    const mobile = viewport.width <= 900;
    if (mobile) await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.getByRole("button", { name: /Workspace:/ })).toBeVisible();
    await page.getByRole("button", { name: /Workspace:/ }).click();
    await expect(page.getByRole("listbox")).toBeVisible();
    await expectNoDocumentOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-workspace-selector.png`), fullPage: true });
    await page.keyboard.press("Escape");
    if (mobile) await page.locator(".sidebar").getByRole("button", { name: "Close navigation" }).click();

    await page.goto("/board");
    await page.getByRole("button", { name: /Switch to dark theme/ }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-board-dark.png`), fullPage: true });

    await page.goto("/tasks");
    await page.getByRole("button", { name: `Responsive task ${viewport.name}` }).click();
    await expect(page.getByRole("dialog", { name: `Responsive task ${viewport.name}` })).toBeVisible();
    await expectNoDocumentOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`${viewport.name}-task-detail.png`), fullPage: true });
    if (viewport.width <= 640) await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();
    else if (viewport.width <= 900) await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
    else await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  });
}
