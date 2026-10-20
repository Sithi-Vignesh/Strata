# Automated browser testing

The release browser matrix includes `e2e/final-review.spec.ts` for two-workspace global/workspace scoping, revocation, and the retained-activity ID regression. `e2e/responsive.spec.ts` captures 1440×900, 1024×768, 768×1024, and 390×844 screenshots for the new dashboards, task scopes, selector, Kanban, and task drawer, including a dark-theme board capture.

Strata's Playwright suite exercises the real React frontend, Vite proxy, FastAPI backend, session cookies, and custom database storage. It is the Phase P1 foundation for the broader P4 acceptance suite.

## Safety and architecture

`frontend/playwright.config.ts` runs Chromium against fixed loopback ports (`15173` for Vite and `18100` for FastAPI). Playwright's `frontend/e2e/global-setup.ts` owns the complete service lifecycle and:

1. creates a uniquely named `strata-e2e-*` directory under the operating-system temporary directory;
2. proves that separate `product` and `sql` directories are descendants of that temporary root;
3. starts one Uvicorn worker with explicit `STRATA_PRODUCT_DATA_DIR`, `STRATA_DATA_DIR`, `STRATA_FRONTEND_ORIGIN`, and insecure-local-cookie settings;
4. waits for backend health before starting Vite, then verifies health through the real Vite proxy;
5. returns a global teardown that terminates both owned process trees (using their captured PIDs on Windows) and removes only the verified temporary root, including after test failures;
6. provides a nonce-bound restart request inside that temporary root so the P4 journey can gracefully reopen the owned backend against the same disposable stores without any production control endpoint.

The runner never falls back to `data/strata`, `data/dbthon_demo`, or manual-demo storage. Invalid ports, equal ports, storage escaping the generated root, startup failure, and occupied ports fail the run. Tests use unique identities and run with one worker so they never depend on ordering or shared developer accounts.

## Install

From PowerShell:

```powershell
# From the repository root:
cd frontend
npm install
npm run e2e:install
```

`@playwright/test` is a project dev dependency. `e2e:install` installs only Chromium into Playwright's user cache; it does not install a system-wide browser.

## Run

```powershell
# Validate E2E TypeScript and list discovered tests without starting services.
npm run e2e:typecheck
npm run e2e:list

# All browser tests, headless.
npm run e2e

# Interactive troubleshooting.
npm run e2e:headed

# One file or category.
npx playwright test e2e/auth.spec.ts
npx playwright test --grep "@security"
npx playwright test --grep "@responsive"
```

The environment starts and stops automatically. Do not start the normal development backend on the E2E ports. Override ports only when necessary:

```powershell
$env:STRATA_E2E_BACKEND_PORT = '18101'
$env:STRATA_E2E_FRONTEND_PORT = '15174'
npm run e2e
```

## Fixtures and selectors

`frontend/e2e/fixtures.ts` provides unique accounts, real-browser registration/login, workspace/project helpers, authenticated API setup/assertions, and overflow checks. Primary acceptance journeys use role, label, and accessible-name locators. API setup is reserved for secondary test data and explicit authorization assertions; it does not replace the main browser interaction journeys.

Independent-user scenarios create distinct browser contexts and assert both identity and different opaque session-cookie values. Browser authentication is never bypassed.

## Suites

- `auth.spec.ts`: registration, login failure/success, refresh persistence, logout, protected redirects, independent contexts and cookie properties.
- `workspace.spec.ts`: collaborative workspace creation/switching, projects, navigation, stale workspace data, and command palette.
- `tasks.spec.ts`: create, status, priority, due date, edit, refresh persistence, detail, and deletion.
- `collaboration.spec.ts`: two-user membership, assignment, status update, and cross-session visibility.
- `security.spec.ts`: protected routes, isolation before membership, membership revocation, and task/workspace API denial using the affected user's session.
- `responsive.spec.ts`: login, dashboard, projects, tasks, Kanban, Inbox, navigation mode, task detail, overflow assertions, and screenshots at 1440×900, 1024×768, 768×1024, and 390×844.

## Failure artifacts and reports

- HTML report: `frontend/playwright-report/` (`npm run e2e:report`)
- Traces, screenshots, videos, and explicit responsive screenshots: `frontend/test-results/artifacts/`
- Automatic screenshots: failures only
- Traces and videos: retained on failure

These generated directories are ignored by Git. In CI the suite emits a line reporter plus the HTML report and retries one time; local runs do not retry, so flaky behavior remains visible.

## Troubleshooting

- **Executable missing:** run `npm run e2e:install`.
- **Port already in use:** stop the process on `15173`/`18100`, or set both E2E port variables to unused values.
- **Python cannot launch:** recreate the repository `.venv` according to `docs/development.md`; global setup intentionally uses that environment.
- **Health timeout:** inspect the prefixed `[backend]` and `[frontend]` output. Global setup cleans its processes and temporary storage after failure.
- **Open a trace:** `npx playwright show-trace <trace.zip>`.
- **Never point E2E at developer data:** the runner has no option to accept database paths. If the isolation check fails, fix the runner rather than bypassing it.

## P4 extension

P4 can add categorized specs under `frontend/e2e`, reuse the helpers and real service lifecycle, and run focused categories with `--grep`. Ownership transfer, notes, handoffs, activity, notification detail, search, appearance, SQL Lab, persistence, and wider concurrency journeys should extend this foundation rather than introduce a second server runner or fixture system.
