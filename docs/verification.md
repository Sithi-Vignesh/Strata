# Strata final verification report

Date: 19 October 2026 (Asia/Calcutta). Branch: `main`. HEAD at verification: `04b66c5e54968566062c6083478527aa28c743c3`.

## Readiness

**READY WITH DOCUMENTED LIMITATIONS.**

The final full P4 acceptance run passed all 13 required automated stages. It included **782 backend tests**, **94 frontend tests**, and **15 real Chromium tests**, plus type checks, production build, live HTTP/restart, benchmark/integrity, whitespace, and cleanup checks. The optional persistent-demo readiness stage was skipped because the owned demo was initialized but not running; it was not a required stage.

Automated and manual evidence are distinct. After the automated runner reported `READY FOR FINAL MANUAL REVIEW`, the user separately reported **8/8 manual re-review checks passed**. That manual result is user-reported and is not counted among the 13 automated stages or the automated test totals. The earlier 12-check manual result described in [adversarial-hardening.md](adversarial-hardening.md) predates final P4 and is retained only as historical phase evidence.

## Work inherited from Astra

The interrupted hardening run had already implemented and tested:

- retained B+ tree separator bounds during deletion, including variable-width keys;
- B+ tree operation before-images for recoverable split/write failures;
- three-leaf packing when a legal large key cannot fit a two-leaf split;
- compensation for failed task/workspace cascades and ownership-transfer relocation;
- unsafe-request Origin validation and explicit Vite `changeOrigin: false` behavior;
- UTF-8 encodability validation for malformed Unicode;
- strict JSON integer fields for assignment and ownership transfer;
- adversarial API, storage, service, concurrency, restart, and proxy tests.

The detailed reproductions and regression names are recorded in [adversarial-hardening.md](adversarial-hardening.md).

## Completion work

The interrupted frontend audit was finished. Confirmed defects and fixes were:

- A retained `refreshTasks` callback could apply project A data after switching to project B. The provider now checks the current selected-project generation before starting or applying a refresh.
- A 401/403 task refresh retained revoked workspace/project/member/task data. Sensitive product state is now cleared before showing the error state.
- Successful task mutations followed by a failed refresh kept the form open, allowing accidental duplicate submission. A committed mutation now closes the form and presents a refresh warning.
- An open task detail held a stale object and remained visible after deletion or access loss. It now follows the canonical task list and closes when the task disappears.
- Authentication bootstrap/login/register/logout responses were not consistently ordered around session-expiry changes. All auth operations now participate in the same request generation, and late responses cannot restore stale authentication state.
- The hardening prompt had accidentally been pasted into `src/strata_engine/__init__.py`, producing an import-time syntax error. The inserted prompt was removed; the legitimate module export surface was unchanged.

Controlled frontend regressions cover rapid workspace switching, stale project-task refreshes, deleted selections, authorization loss, canonical task-detail refresh, and responses arriving after authentication changes.

## Final P4 automated acceptance results

The canonical run was `20261019T131431Z-62cbb4e4` in full mode. Its repository-local report is stored under `.verification/acceptance/final-review-full/`; the directory is intentionally ignored and no machine-specific absolute path is required to locate it. Commands ran from the repository root unless marked `frontend`.

| Check | Command | Result |
| --- | --- | --- |
| Required stages | `.\.venv\Scripts\python.exe scripts\run_acceptance.py --full` | **13/13 passed**; 1 optional stage skipped |
| Backend, integrity, and concurrency regression | acceptance runner backend stage | **782 passed**, 7 deprecation warnings |
| Frontend unit and component tests | acceptance runner frontend stage | **94 passed** |
| Real Chromium browser acceptance | acceptance runner browser stage | **15 passed** |
| Acceptance runner self-tests | acceptance runner self-test stage | **7 passed** |
| TypeScript and production build | acceptance runner TypeScript/build stages | Passed |
| Playwright TypeScript checks | acceptance runner Playwright typecheck stage | Passed |
| Live HTTP collaboration and restart | acceptance runner HTTP/restart stage | Passed |
| P2 benchmark and integrity | acceptance runner smoke and full-profile stages | Passed |
| Git whitespace and disposable-storage cleanup | acceptance runner final stages | Passed |

The warnings are the existing Starlette `TestClient`/httpx and per-request cookie deprecations. No dependency or assertion was weakened to suppress them.

## Concurrency and deployment scope

Supported deployment is one backend process/worker and one engine owner per local database directory, with concurrent request threads serialized by the engine-owned reentrant `DatabaseLock`. Catalog, table, index, SQL, adapter, and product-service operations reuse that lock. Table scans materialize snapshots before releasing it.

This design prevents supported-path lock cycles through coarse serialization. It is **deadlock prevention, not deadlock detection**. Lock acquisition has a 30-second deadline and API timeouts are retryable HTTP 503 responses. The OS directory lease rejects a second engine/process before it opens storage.

## Known limitations

- No multi-process shared-file execution, multiple backend workers, or network-filesystem guarantee.
- No ACID transaction manager, WAL, fsync contract, general statement rollback, or arbitrary-crash recovery.
- Compensation covers recoverable in-process failures only and requires recovery writes to succeed; repeated I/O faults can leave partial state.
- Detached B+ tree pages are retained and counted rather than reclaimed.
- Raw page/buffer/heap APIs require single-threaded use or an enclosing engine operation context.
- Coarse locking limits throughput and fairness; snapshot scans use memory proportional to result size.
- Logical IDs use `MAX + 1` and may be reused after deleting the highest ID.
- Same-field concurrent edits are last-completed-write-wins; clients refresh rather than receive push updates.
- Requests already authenticated may complete concurrently with logout. A later 401 clears frontend authentication and product state.
- The SQL console uses a separate demonstration database and direct trusted engine access bypasses product authorization by design.
- Automated P4 evidence, real Chromium coverage, and the user-reported 8/8 manual re-review are separate evidence streams; none is represented as a substitute for another.

## Repository state

No commit, push, reset, clean, dependency change, or development-data deletion was performed. The working tree intentionally remains modified and untracked with the inherited implementation, hardening fixes, new tests, smoke script, and documentation. Consult `git status --short` for the authoritative current file list.
