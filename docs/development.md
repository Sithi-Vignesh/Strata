# Development, verification and manual acceptance

## Environment

Use PowerShell from the repository root. Python >=3.10 and the Node/npm versions compatible with the committed frontend lockfile are required. This sprint verified the existing virtual environment on Python 3.12.10; no package versions were changed.

~~~powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd frontend
npm ci
cd ..
~~~

Installation is only needed for a new environment. The existing environment already contained the dependencies. If its launcher reports a missing base Python, verify that a compatible Python installation is available with `py -0p` or `python --version`. In this sprint the `.venv` launcher worked outside the restricted agent runner; no replacement was necessary. Do not delete a working environment or change package versions to address a runner permission problem.

For a genuinely broken environment, create a separate .venv-repaired with a verified compatible interpreter, install this project there and run all tests before replacing anything.

## Start a clean local demo without touching existing data

Backend terminal, repository root:

~~~powershell
$env:STRATA_PRODUCT_DATA_DIR = Join-Path $PWD 'data\manual-demo\product'
$env:STRATA_DATA_DIR = Join-Path $PWD 'data\manual-demo\sql'
$env:STRATA_SESSION_COOKIE_SECURE = 'false'
.\.venv\Scripts\python.exe -m uvicorn strata_backend.main:app --host 127.0.0.1 --port 8000 --workers 1
~~~

Frontend terminal:

~~~powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
~~~

Open **http://127.0.0.1:5173**. The frontend proxies /api and /health to 127.0.0.1:8000, so browser cookies work on the same origin. Backend health is http://127.0.0.1:8000/health; API docs are http://127.0.0.1:8000/docs. Use the same frontend hostname consistently in both browser sessions. The optional STRATA_FRONTEND_ORIGIN default is http://localhost:5173; same-origin proxy requests do not require a CORS override.

Startup creates/validates tables and indexes automatically. Register accounts through the UI; there is no usable seed password. New product databases contain the historical seed account and workspace, but newly registered users cannot see those resources without membership.

The demo paths above are ignored by Git. Existing data/strata and data/dbthon_demo are untouched. To start another clean demo, choose a new pair of directories such as data/manual-demo/run2/product and data/manual-demo/run2/sql. Never point both engines to the same directory, delete files under a running backend, or remove .strata.lock to bypass ownership.

Use Ctrl+C in each terminal. Wait for backend shutdown to finish before restarting with the same directories. Do not use multiple workers or open another engine on those files. A second opener fails with DatabaseInUseError by design. Keep data on local disk. Back up the entire database directory after normal shutdown.

The server reads environment variables from the process, not automatically from .env. For existing development data, omit the two directory overrides (defaults are data/strata and data/dbthon_demo). STRATA_SESSION_COOKIE_SECURE must be true only when serving through HTTPS; setting it true on this HTTP demo prevents cookie authentication.

## Automated checks

From the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_product_api.py tests/test_product_auth.py tests/test_product_authorization.py tests/test_product_membership.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py tests/test_adversarial_concurrency.py tests/test_adversarial_service.py
.\.venv\Scripts\python.exe scripts\smoke_test.py
cd frontend
npm test
npm run typecheck
npm run build
cd ..
git diff --check
git status --short
~~~

Pytest uses isolated temporary directories. The smoke script starts a real loopback Uvicorn server on an available ephemeral port, creates three independent HTTP sessions, tests collaboration/authorization/removal/concurrency, stops normally, reopens the database and verifies records and every product index. It also invokes the deterministic contention suite. PASS is printed only after assertions; failures return a nonzero exit code. No browser automation is required for this script.

To also start Vite on 5173 and verify its authenticated proxy to an isolated backend
on 8000, stop other servers on those ports and run:

~~~powershell
.\.venv\Scripts\python.exe scripts\smoke_test.py --frontend
~~~

Both servers are stopped by the script. This verifies startup, module serving and
cookie transport; it does not perform human browser interaction.

The core deadlock experiment uses opposite table orders and an event set before the competing worker acquires the shared lock. The first worker does not wait for the second to acquire that lock. Other tests observe acquisition attempts across each supported path. All workers have bounded joins; no arbitrary sleeps are used to establish contention. A short acquisition deadline is used only by the timeout-specific test.

The existing dependency stack emits a Starlette/httpx deprecation warning and six per-request-cookie deprecation warnings. These do not fail the suite; dependencies were not changed to suppress them.

## Manual acceptance reference runbook

The user reported all 12 manual browser acceptance checks passed on 15 October 2026. The scenarios below remain a reusable demonstration runbook, not a new acceptance gate. Final hardening evidence is in [adversarial-hardening.md](adversarial-hardening.md).

Use a normal browser profile for User A and a separate profile/incognito session for User B. Two tabs in the same profile share a cookie and are not independent accounts.

- Register A and B independently; verify their displayed identities.
- A creates a collaborative workspace in the sidebar.
- A enters B's registered email in Member email and selects Add.
- B selects Refresh workspace, then selects the shared workspace.
- A opens Projects, creates a project and opens its tasks.
- A creates a task with B as assignee. B refreshes and sees it in My Tasks.
- B changes status on Tasks or Board and adds a note in task details.
- A refreshes and sees the changed status and B's note. B edits/deletes a disposable note; A has no edit/delete controls for B's note.
- Edit a project description; rename the collaborative workspace as owner.
- B cannot perform owner-only membership/workspace actions. A third account cannot access the shared resources; private workspaces remain isolated.
- A removes B; B refreshes and loses access. A sees B's task unassigned, with note/creator history retained.
- Re-add B and transfer ownership; exactly one owner is displayed, and only the new owner has membership controls.
- Refresh both sessions; log out/in; verify persisted state.
- Stop the backend with Ctrl+C, wait for shutdown, restart with the same environment variables, and verify projects/tasks/notes and sessions.
- Delete disposable tasks (including notes), then their empty project, then an empty collaborative workspace. Non-empty project/workspace deletion shows an error.
- Run tests/test_concurrency.py and scripts/smoke_test.py to demonstrate bounded contention and normal restart persistence.
- Open SQL Console and run a profiled query on the separate SQL demo data.

Shared views update on refresh; this sprint does not add real-time push. Same-field edits use the last completed write. The completed manual acceptance and automated hardening evidence cover different aspects of the demonstration.
