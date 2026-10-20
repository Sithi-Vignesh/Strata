# Reproducible demo environment

The demo remains compatible with the global/workspace navigation split. `Atlas Product Team` appears in the workspace selector; Common Dashboard and All Tasks may also include the signed-in demo account's other currently accessible workspaces. My Tasks and Workspace Dashboard are limited to the selected workspace. Initialization does not rewrite retained task activity.

STRATA's persistent demo runs the real backend, frontend, product APIs, authentication, and SQL engine against storage reserved for this purpose. It does not use or reset the normal `data/strata` and `data/dbthon_demo` directories.

## Prerequisites

- Python 3.10+ with the repository `.venv` installed (`pip install -e ".[dev]"`).
- Node.js and the packages in `frontend/node_modules` (`npm install` in `frontend`).
- Playwright Chromium (`npm run e2e:install`) only for the optional browser smoke test.
- Ports `18080` (backend) and `15174` (frontend) available. Alternative ports can be supplied to `start`.

Run commands from the repository root in PowerShell:

```powershell
python scripts/demo.py init
python scripts/demo.py start
python scripts/demo.py verify --json
python scripts/demo.py stop
python scripts/demo.py reset --yes
```

When the virtual environment is not activated, use `.\.venv\Scripts\python.exe` in place of `python`.

`init` is idempotent and repairs a partially populated demo by finding or creating each named entity. `start` also runs `init`, preserves prior demo data, rejects occupied ports, and returns success if its own healthy supervisor is already running. `verify` has bounded requests, emits structured pass/fail output, writes `.verification/demo/verification.json`, and returns a nonzero exit code on failure. `stop` asks the owning supervisor to stop only the child processes it launched. A stale PID is never enough authority to terminate a process.

`reset --yes` deletes `.verification/demo` only after its complete marker (root plus both exact storage paths) validates and all recorded services are stopped. An unmarked, moved, malformed, or running directory is rejected. Reset is the only command that removes the persistent demo dataset.

URLs after startup:

- Frontend: `http://127.0.0.1:15174`
- Backend health: `http://127.0.0.1:18080/health`
- Logs: `.verification/demo/logs/backend.log` and `frontend.log`

## Public demo data and credentials

| Role | Email | Password |
|---|---|---|
| Demo Owner | `owner@demo.strata.local` | `Strata-Demo-Owner-2026!` |
| Demo Collaborator | `collaborator@demo.strata.local` | `Strata-Demo-Collaborator-2026!` |

These are deliberately demo-only local credentials. Do not use them outside this isolated environment.

The collaborative workspace is **Atlas Product Team**, with **Website Redesign**, **Mobile App Launch**, and **Platform Reliability** projects. Seven tasks cover `TODO`, `IN_PROGRESS`, and `DONE`; low, medium, and high priority; both people and unassigned work; overdue, today, and upcoming dates; notes; assignment notifications; and task activity. **Publish responsive landing page** is the featured owner-to-collaborator handoff.

## Two-user walkthrough

1. Open one private browser window, sign in as Demo Owner, and select Atlas Product Team.
2. Open **Tasks**, then **Publish responsive landing page**. Observe the collaborator assignment, today due date, notes, and activity history containing the handoff.
3. In a separate private window, sign in as Demo Collaborator and select Atlas Product Team.
4. Open **My Tasks**. The featured task is present. Open **Inbox** and inspect its assignment notification.
5. Open the task, change its status (for example to `DONE`), and add a note. These are normal authenticated application operations, not seed shortcuts.
6. Return to the owner window, refresh, and inspect the new status, note, and activity. Stop and start the demo; the change remains because both stores are persistent.

The initializer is deterministic but does not undo walkthrough edits. Use `reset --yes`, `init`, and `start` when a pristine presentation is required.

## SQL Lab sequence

The SQL Lab is a separate database at `.verification/demo/data/sql`; it is not the product store. Initialization creates `demo_projects` and `demo_work_items`, inserts six rows, and creates a programmatic single-column index named `demo_work_items_status_idx`. SQL `CREATE INDEX` is not supported, so the initializer correctly uses the engine API for that one step.

The following statements have been verified against the current engine:

```sql
SELECT id, title, status, effort
FROM demo_work_items
ORDER BY effort DESC, id;

SELECT id, title
FROM demo_work_items
WHERE status = 'TODO'
ORDER BY id;

SELECT status, COUNT(*), SUM(effort), AVG(effort)
FROM demo_work_items
GROUP BY status
ORDER BY status;

SELECT demo_projects.name, demo_work_items.title, demo_work_items.status
FROM demo_projects
INNER JOIN demo_work_items
  ON demo_projects.id = demo_work_items.project_id
ORDER BY demo_work_items.id;
```

The initializer itself demonstrates supported DDL and insertion with statements equivalent to:

```sql
CREATE TABLE demo_projects (id INTEGER, name VARCHAR(64), lead VARCHAR(64));
INSERT INTO demo_projects VALUES (1, 'Website Redesign', 'Avery');
```

Do not rerun those two statements after initialization because the table and row already exist. To demonstrate profiling, execute the indexed `WHERE status = 'TODO'` query and inspect the `IndexScan` profile plus actual page/entry/row counters. A join correctly has no single-table scan profile.

## Presentation-ready run (6–8 minutes)

1. Run `start`, then `verify --json`; point out the independent storage paths and all green checks.
2. Sign in as owner and show the Atlas workspace, three projects, task variety, featured task notes, and handoff activity.
3. Sign in independently as collaborator; show My Tasks and Inbox, then update the featured task and add a note.
4. Refresh the owner view to show the shared update and activity.
5. Run the four read-only SQL examples, highlighting `GROUP BY`, aggregation, the two-table nested-loop `INNER JOIN`, and the real indexed profile.
6. Run `stop`, `start`, and `verify --json` to prove persistence, then `stop` for a clean handoff.

## Automated browser smoke test

With the demo running:

```powershell
cd frontend
npm run demo:e2e
```

This uses the P1 Chromium fixtures and two independent browser contexts. It intentionally has no disposable global setup because it targets the explicitly running persistent demo.

## Troubleshooting and accurate claims

- **Port already in use:** choose alternatives, for example `python scripts/demo.py start --backend-port 18081 --frontend-port 15175`. Set `STRATA_DEMO_FRONTEND_PORT=15175` for the demo Playwright test.
- **Missing `.venv` or frontend packages:** install prerequisites. Startup fails before opening a service.
- **Interrupted startup:** the supervisor stops the children it created. A later `start` removes stale metadata only when none of its recorded processes are live.
- **Unexpected supervisor loss with live recorded children:** management fails closed rather than risk killing a recycled/unrelated PID. Inspect the logged command/process and stop it manually before removing stale metadata.
- **Partial initialization:** rerun `init`; named entities and notes are reconciled without duplication.
- **Changed demo credentials:** initialization rejects an existing same-email account if the documented password does not authenticate.
- **Database scope:** STRATA supports the documented SQL subset and persistent page/index storage. It does not claim crash-safe ACID transactions, SQL `CREATE INDEX`, or deadlock detection.
- **Concurrency wording:** demonstrate bounded database-busy responses and serialized compound operations as deadlock prevention by design. Do not claim a general deadlock detector. Index claims must come from the returned `IndexScan` profile, not timing alone.

Future P4 automation can call `python scripts/demo.py verify --json` for this persistent environment, but its master acceptance path should continue using disposable storage. The JSON status, named checks, bounded network operations, output file, and exit code are intended for composition.
