# Acceptance testing and release verification

Final-review coverage adds activity-generation compatibility, Common Dashboard, Workspace Dashboard, All Tasks, workspace-scoped My Tasks, revocation, navigation scope clarity, and responsive visual artifacts to the P4 browser and backend stages. The canonical commands remain `python scripts/run_acceptance.py --smoke` and `python scripts/run_acceptance.py --full`.

`scripts/run_acceptance.py` is STRATA's release-level orchestrator. It coordinates the existing P1 Playwright environment, P2 benchmark/integrity harness, P3 optional persistent-demo verifier, backend and frontend tests, live HTTP restart smoke, build checks, and cleanup evidence. It does not replace or duplicate those systems.

## Commands

Run from the repository root in PowerShell:

```powershell
# Default bounded profile
python scripts/run_acceptance.py
python scripts/run_acceptance.py --smoke

# Complete backend/browser suite and full P2 benchmark
python scripts/run_acceptance.py --full

# Machine-readable output or selected artifact directory
python scripts/run_acceptance.py --smoke --json
python scripts/run_acceptance.py --full --output .verification/acceptance/release-candidate
```

Use `.\.venv\Scripts\python.exe` instead of `python` when the virtual environment is not activated. `--smoke` and `--full` are mutually exclusive. Smoke is the default; it is useful feedback but is not a substitute for a successful full run.

Prerequisites are Python 3.10+, installed project development dependencies, Node/npm, `frontend/node_modules`, and Playwright Chromium (`npm run e2e:install` in `frontend`). The runner does not install or modify dependencies.

## Architecture and dependencies

Each subprocess has a fixed timeout, dedicated log, duration and exit code. Stage statuses are exactly `passed`, `failed`, `skipped`, `blocked`, and `not_executed`. Failure categories distinguish missing dependencies, timeouts, unsafe storage, invalid reports, interruption, cleanup failures, prerequisite failures, and ordinary subprocess failures.

Stages are dependency/repository preflight; runner self-tests; backend/integrity/concurrency regression; frontend tests; TypeScript and production build; real Chromium acceptance; real HTTP collaboration/restart smoke; P2 benchmark/integrity smoke; optional P2 full profile; optional P3 demo verification; `git diff --check`; and cleanup audit.

Only true prerequisites block dependents. A failed backend suite does not hide frontend evidence. Browser execution depends on the build and Playwright type-check. Cleanup always executes. Any required stage that fails, is blocked, skipped, or not executed makes the overall run fail.

The P3 stage runs only when `.verification/demo` has the exact ownership marker and an already-running, ready supervisor. An absent or stopped demo is optional `skipped/demo_unavailable`, never passed. The runner never initializes, starts, stops, or resets persistent demo data.

## Isolation and cleanup

- Pytest uses temporary-directory fixtures.
- P1 creates distinct product and SQL stores beneath a verified `strata-e2e-*` OS temporary root.
- The P4 release journey uses a nonce-bound file inside that root to gracefully restart the owned backend against the same stores while Chromium retains its real cookies. No production endpoint is added.
- P2 creates only a verified `strata-benchmark-*` root and reports its removal.
- HTTP smoke uses the existing `strata-smoke-*`/`strata-web-smoke-*` roots.
- The runner snapshots matching temporary roots and fails cleanup if a newly created root remains.
- Reports default to ignored `.verification/acceptance`; developer stores under `data/strata` and `data/dbthon_demo` are never selected.

On timeout or interruption, the runner terminates only the subprocess tree it created. It does not search for processes by port or kill unverified PIDs.

## Reports and failures

Every run writes:

- `acceptance.json`: stable schema version 1, metadata, every stage result, counts, durations, failure categories, cleanup and verdict.
- `summary.md`: readable release summary.
- `logs/<stage>.log`: complete combined subprocess output.
- `benchmark-smoke/` and, in full mode, `benchmark-full/`: validated P2 evidence.

The report records Git commit/dirty state, Python/Node/npm/OS versions, run ID and timestamps. `--json` suppresses progress and emits the final report to stdout. A required failure or cleanup failure returns a nonzero exit code.

Playwright failures retain screenshots, videos and traces under `frontend/test-results/artifacts`. Inspect them with:

```powershell
cd frontend
npx playwright show-trace test-results\artifacts\<test-name>\trace.zip
npm run e2e:report
```

## Coverage matrix

“Yes” means assertions exercise the behavior at that layer; filenames alone are not evidence. A dash means the layer is not appropriate or implemented.

| Feature | Unit | API/service | Browser | Persistence | Concurrency |
| --- | --- | --- | --- | --- | --- |
| Authentication | Yes | Yes | Register, invalid login, logout | Sessions reopen | Login/logout race |
| Sessions | Yes | Yes | Independent contexts, refresh | Backend restart | Expiry/logout contention |
| Workspaces | Yes | Yes | Create, switch, isolate | Restart journey | Serialized mutations |
| Membership | Yes | Yes | Add/remove, role controls | Restart journey | Revocation races |
| Ownership transfer | Yes | Yes | Transfer/control change | Backend suite | Transfer/removal contention |
| Projects | Yes | Yes | Create, navigate, delete | Restart journey | Service serialization |
| Tasks | Yes | Yes | Create/edit/delete/detail | Restart journey | Update/delete contention |
| Due dates | Yes | Yes | Input and rendered states | Restart journey | Sidecar consistency |
| Kanban | Yes | Yes | Accessible status move | Restart journey | Task-update tests |
| My Tasks | Yes | Yes | Cross-workspace listing | Restart journey | Membership filtering |
| Notes | Yes | Yes | Collaborator adds note | Restart journey | Concurrent ID allocation |
| Handoffs | Yes | Yes | UI handoff/activity | Restart journey | Assignment serialization |
| Activity | Yes | Yes | Actors, changes, pagination | Restart journey | Orphan checks |
| Notifications | Yes | Yes | Count/read/unread/all/dismiss/navigation/pagination | Restart journey | Mutation tests |
| Search/filter/sort | Yes | Yes | Server-backed controls | — | Bounded queries |
| Command palette | Yes | — | Keyboard navigation | — | — |
| Themes | Yes | — | Light/dark/system | Browser reload | — |
| SQL Lab | Yes | HTTP | P1 UI/API workflow | P2 reopen | Adapter serialization |
| Indexing | Yes | Profile API | Profile presentation | Reopen validation | Post-contention validation |
| Integrity | Yes | Service assertions | Authorization observations | P2 reopen | P2 mixed workload |
| Revocation | Yes | Yes | Stale UI/API denial | Restart then revoke | Revocation races |
| Persistence | Yes | HTTP restart | Graceful backend restart | Yes | Reopen after contention |
| Concurrency | Yes | HTTP smoke | Shared-user actions | Reopen validation | Bounded controlled races |
| Responsive layout | Yes | — | Four viewports/mobile nav | — | — |
| Task drawer accessibility | Yes | — | Dialog semantics/Escape | — | — |
| Error/pending states | Yes | Adversarial API | Pending logout/artifacts | — | Controlled response races |

## Runner reliability tests

`tests/test_acceptance_runner.py` verifies a nonzero subprocess, timeout, missing executable, malformed benchmark JSON, interrupted/browser/unsafe-storage classifications, leaked temporary storage, unavailable optional demo, dependency blocking, persisted report schema, and non-passing verdicts. These tests are required in both modes.

## Troubleshooting

- **Missing Chromium:** run `cd frontend; npm run e2e:install`. Browser failure is not skipped.
- **Occupied P1 ports:** identify the process using 18100 or 15173. P1 does not terminate unrelated listeners.
- **Timeout:** inspect the stage log. A timeout fails the stage.
- **Invalid benchmark report:** inspect P2 output. The runner validates schema, workloads, timings, correctness sections and cleanup, not just exit zero.
- **Cleanup failure:** inspect reported paths; never remove an unfamiliar directory without verifying its parent and name.
- **Demo skipped:** start the owned demo separately only if desired; core acceptance does not depend on it.
- **Interrupted run:** confirm no owned child remains, then rerun. A missing cleanup result prevents a passing verdict.

## Known limitations

- Browser automation verifies behavior and accessibility state, not subjective visual polish; final human review remains required.
- Timings are observations, not absolute release thresholds.
- STRATA provides serialization-based deadlock prevention and bounded busy behavior, not deadlock detection.
- Persistence covers normal graceful shutdown/reopen, not crash-safe ACID, WAL recovery, or power-loss atomicity.
- Multi-process writers are intentionally rejected; acceptance uses one backend writer.
- Real-time push is not implemented, so the two-user journey refreshes where required by the product contract.

## Release checklist

1. Confirm the dirty tree contains only understood work; never clean inherited changes.
2. Install fixed project/frontend dependencies and Chromium.
3. Run smoke and inspect every non-passed stage.
4. Run full acceptance for release evidence.
5. Confirm cleanup and that no developer storage appears in commands/logs.
6. Inspect browser artifacts for failures.
7. Review benchmark correctness/profile evidence without latency gates.
8. Perform final manual browser/presentation review.
9. Archive JSON, Markdown, logs, benchmarks, and relevant browser artifacts.
