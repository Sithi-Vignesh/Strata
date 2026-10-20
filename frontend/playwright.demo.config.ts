import { defineConfig, devices } from "@playwright/test";

const frontendPort = Number(process.env.STRATA_DEMO_FRONTEND_PORT ?? "15174");

export default defineConfig({
  testDir: "./demo-e2e",
  outputDir: "./test-results/demo-artifacts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report-demo", open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    ...devices["Desktop Chrome"],
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
