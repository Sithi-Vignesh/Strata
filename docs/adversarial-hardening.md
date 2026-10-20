# Strata Adversarial Hardening Report

Date: 15 October 2026 (Asia/Calcutta). Scope: the local academic demonstration, one backend worker, one engine owner per database directory, local disk. Existing development/manual-demo databases were preserved. All attack and fault tests used synthetic users and temporary databases.

## A. Executive verdict

This document records the completed adversarial-hardening phase and its results at that time. The user reported all 12 manual browser acceptance checks passed before this phase; the phase supplemented that acceptance with reproduced defects, targeted fixes, and automated evidence, but did not itself claim a new human/browser acceptance run.

The later final P4 acceptance run and the separate user-reported 8/8 manual re-review are documented in [verification.md](verification.md). Their larger test totals supersede this report as release evidence; the results below remain the historical evidence for the hardening phase and are not combined with or presented as the final P4 totals.

## B. Attack surface coverage

| Area | Actually exercised |
| --- | --- |
| Authorization/tenant isolation | Three registered users (owner/member/outsider); 25 resource route/method combinations tested as outsider, removed member and unauthenticated caller (75 denials); another 18 owner/member/personal-workspace/indirect-reference/spoofing denials. Each compares every product row and index before/after. Fixture shutdown/reopen verifies persisted results. Existing API tests retain positive collaboration and creator/author rules. |
| Authentication/sessions | Real registration/login/logout, independent cookies, invalid credentials, canonical email, missing/malformed/expired/revoked sessions, inactive/deleted accounts, cookie flags and Secure configuration; old-token reuse after numeric session-ID reuse; controlled expiry/logout races in both orders. In-flight requests already authenticated before logout may finish; subsequent requests with the revoked token fail. |
| CSRF | HTTP requests carrying cookies and an untrusted same-site alternate-port Origin; logout reproduction; null/foreign origins, Referer/Fetch Metadata fallback, trusted origin, configured frontend and headerless client acceptance. Body routes reject text/plain/form payloads. Real Vite smoke sends the actual frontend Origin. No connected browser was available, so this round did not execute browser-generated attack traffic. |
| Concurrency | Existing 21 lock/contention tests plus two process-guard cases and seven additional service contention cases. Same-task patches/creation/deletion, notes, ownership transfer/removal, assignment/removal, sessions, SQL/catalog/table/index/close paths, exception release, snapshot scans and 503 timeout behavior. Events observe an actual competing lock acquisition; joins/processes have deadlines. |
| Storage/indexes | Slotted-page/record boundary and corruption suites; deterministic 180-key variable-width deletes; seeded nullable/duplicate/Unicode insert-update-delete sequences; large-key leaf splits; retained-bound insertions/ranges; RID relocation; pool-size-one eviction/pin accounting; indexed results compared with authoritative scans; repeated normal reopen. |
| Failure recovery | Faults before the second index operation, after node write, and during root allocation after leaf splitting; child/parent cascade deletion faults; assignment rollback; actual full-page ownership relocation followed by promotion failure; failed inverse reporting. Successful compensation compared across close/reopen. |
| Input | Blank/oversized fields, nulls, invalid enums/types, unexpected/missing fields, spoofed author/creator, negative/zero/huge IDs, malformed Unicode in product/auth/SQL/unknown fields, invalid JSON, valid multilingual text/control characters, malformed SQL. Denials preserve data; health remains responsive. |
| Frontend | Controlled out-of-order provider tests cover workspace/project switching, authorization loss, deleted selections, canonical task-detail refresh, committed-mutation refresh failure, session expiry and late authentication responses. |
| Live persistence | Real loopback Uvicorn with independent HTTP sessions, collaboration, removal/assignment cleanup, concurrent updates, normal shutdown/restart and every product index checked. Vite startup/module serving/authenticated proxy verified separately. |

The full suite also covers registration compensation, password hashing outside the database lock, slotted-page capacity/compaction, heap reuse, invalid RIDs, buffer flushing and index lifecycle. No public service, third-party account, uncontrolled stress workload, new dependency or development database was used.

## C. Confirmed findings

Every finding below was reproduced before its fix. Regression results are summarized in section F; intermediate red tests were expected reproductions, not hidden final failures.

### SH-01 — CRITICAL — VARCHAR deletion corrupts heap/index agreement

- Component: B+ tree separator maintenance.
- Reproduction: seed 7031, insert 180 mixed-width VARCHAR keys, reopen, delete in the deterministic shuffled order. Original deletion #14 raises KeyTooLargeError; heap retains logical ID 40 while indexed lookup is empty (167 heap rows versus 166 index entries).
- Root cause: deletion rewrote internal separators to exact right-child minima. A longer replacement overflowed an internal page after the leaf had changed.
- Fix: retain valid composite lower bounds and remove only the boundary adjacent to a detached child. Structural validation enforces left maximum < separator <= right minimum.
- Regression: test_variable_length_deletion_keeps_index_and_heap_consistent_after_reopen, plus retained-bound interleaving/range checks in tests/test_adversarial_storage.py.
- Verification: deterministic deletion, insertion into gaps, duplicates, ranges, additional splits and repeated reopen pass. A separate read-only load of preserved original source confirmed the original mismatch at Table level.

### SH-02 — HIGH — A failed split leaves an index entry for a deleted heap row

- Component: B+ tree exception recovery / Table index maintenance.
- Reproduction: insert 185 indexed INTEGER rows; fail new internal-root allocation during insertion 186, after the leaf split has written pages. Table removes the new heap row, but the original index still returns RID (0,185).
- Root cause: a partially applied tree call raised before Table could record that index action for compensation.
- Fix: per-tree-operation before-images of touched node pages and structural counters, restored on a recoverable exception. Allocated detached pages remain counted; no WAL, general transactions or page reclamation added.
- Regression: test_root_allocation_failure_after_split_restores_index_and_reopens and test_exception_after_node_write_restores_row_and_index (insert/update/delete).
- Verification: pool size 1, scans/searches/counts/structure/pins, reopen and retry all pass. Recovery-write failure remains an explicitly unsupported durability guarantee.

### SH-03 — HIGH — Failed workspace deletion removes access/ownership

- Component: ProductService.delete_workspace.
- Reproduction: create an empty collaborative workspace with owner/member; inject failure deleting the second membership or the workspace after memberships were deleted.
- Root cause: completed child deletions had no inverse; the surviving workspace could lose its owner or all members.
- Fix: restore completed membership deletions in reverse order, attempt all inverses, and raise ProductDeletionCompensationError if restoration is incomplete.
- Regression: workspace cases of test_failed_cascade_restores_children_and_access_after_reopen and failed-compensation reporting.
- Verification: both users retain access, logical rows and indexes match their pre-failure state after reopen.

### SH-04 — HIGH — Ownership rollback uses an obsolete relocated RID

- Component: ProductService.transfer_workspace_ownership.
- Reproduction: fill a membership page with 112 OWNER rows and eight MEMBER rows (4088 bytes including slots); demote an owner, forcing a real relocation; fail target promotion.
- Root cause: OWNER to MEMBER grows the row by one byte; the service discarded Table.update's returned RID and tried restoring the deleted original address.
- Fix: retain the current owner's returned RID for compensation.
- Regression: test_failed_transfer_restores_relocated_owner_after_reopen.
- Verification: genuine full-page relocation asserted; original roles/logical rows/indexes restored and preserved across reopen.

### SH-05 — MEDIUM — Failed task deletion loses earlier notes

- Component: ProductService.delete_task.
- Reproduction: two notes on a task; fail the second note deletion or the parent task deletion.
- Root cause: completed note deletes were not restored after the operation failed.
- Fix: reverse restoration of completed note deletions with explicit incomplete-compensation reporting.
- Regression: task cases of test_failed_cascade_restores_children_and_access_after_reopen and failed-compensation reporting.
- Verification: task/notes and index agreement preserved across reopen after one-shot failure.

### SH-06 — MEDIUM — Legal large index key cannot be split into two leaves

- Component: B+ tree insertion.
- Reproduction: insert a repeated 1500 times, c repeated 1500 times, then b repeated 3000 times. Original third insert raises KeyTooLargeError although each key is within the supported byte limit.
- Root cause: variable-width records can require three leaves; the implementation required a two-leaf partition.
- Fix: retain balanced two-leaf splits normally and pack three leaves when needed, propagating each split through the current ancestor path.
- Regression: test_legal_large_middle_key_can_require_three_leaf_pages for 3000- and 4054-byte middle keys.
- Verification: insertion, duplicate no-op, lookup, structural validation, reopen and deletion pass.

### SH-07 — MEDIUM — Same-site cross-origin logout is accepted

- Component: HTTP mutation origin checks.
- Reproduction: authenticated POST /api/auth/logout with Origin http://testserver:9999 was accepted (204) and revoked the session. The request needs neither JSON nor preflight.
- Root cause: CORS response policy and SameSite=Lax did not reject same-site, different-origin POSTs. CORS does not prevent delivery of simple requests; SameSite is not origin isolation. [MDN CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS), [MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).
- Fix: validate Origin for unsafe /api methods against the browser-facing request origin or configured frontend origin, with Referer/Fetch Metadata fallbacks; reject null/foreign origins. Preserve headerless non-browser clients. Explicitly configure Vite changeOrigin:false so the frontend Host reaches the backend.
- Regression: test_untrusted_origin_cannot_submit_simple_post_with_session_cookie; live smoke includes rejected foreign-origin logout, successful same-origin logout and frontend Origin through Vite.
- Verification: rejected requests leave session/product state unchanged. Browser exploitability is inferred from documented browser rules and the HTTP reproduction; no fresh browser attack was executed because no browser was connected. Initial hypothesis that a missing Content-Type could create a workspace was NOT reproduced: the installed framework returned 422.

### SH-08 — MEDIUM — Malformed Unicode produces server errors

- Component: HTTP request validation/encoding.
- Reproduction: PATCH a task title with a JSON escaped unpaired surrogate (U+D800); original response was HTTP 500. Auth/password and SQL validation/error serialization were checked too.
- Root cause: JSON accepted a string that cannot be encoded as UTF-8; storage/password processing or error rendering encountered it after request parsing.
- Fix: validate request strings and SQL text for UTF-8 encodability; validation responses omit rejected inputs/context and escape error locations, including invalid unknown field names.
- Regression: malformed-Unicode task cases and test_invalid_unicode_in_auth_sql_unknown_fields_and_invalid_json_is_safe.
- Verification: clean 422 responses, no submitted secret values or stack trace, unchanged rows/indexes and successful reopen; valid multilingual text still works.

### SH-09 — MEDIUM — Body IDs silently accept incorrect JSON types

- Component: request schemas for assignment and ownership transfer.
- Reproduction: assignee_user_id string "3" and float 3.0 were accepted (200) and changed assignment; true was coerced to user 1 before permissions were checked.
- Root cause: default integer coercion weakened the public typed-input contract.
- Fix: StrictInt for body ID fields; path IDs retain their normal URL parsing.
- Regression: malformed-ID cases and independent strict assignment/ownership review cases.
- Verification: bool/string/float body IDs return 422 before mutation; valid integer IDs and all existing collaboration tests pass. This was not an authorization bypass.

## D. Unconfirmed risks and unsupported configurations

No unauthorized cross-tenant read/write or supported-path deadlock was reproduced. No arbitrary-crash recovery, multi-process write concurrency, network filesystem safety or production security certification is claimed. The POSIX lease branch was not executed on this Windows host. Browser-originated CSRF traffic was not executed in this round; the HTTP evidence and browser-rule inference are explicitly separated above.

Repeated faults during inverse writes are a demonstrated limitation: regression tests deliberately fail restoration, verify an explicit error and that remaining inverses are attempted. They do not assert full rollback in that unsupported failure condition. No SQL multi-statement or multi-row atomicity guarantee has been added.

## E. Database concurrency assessment

The existing coarse engine-owned reentrant lock remains defensible for the documented configuration. No synchronization architecture replacement was necessary.

| Entry path | Acquisition order / protected scope |
| --- | --- |
| ProductService / authentication session operation | Engine DatabaseLock -> catalog/table/index calls reenter the same lock; permission checks, ID allocation and writes stay within it. Password hashing/verification occurs outside it. |
| SQL / EngineAdapter | Engine DatabaseLock -> parser/binder/planner/operator lifecycle and result materialization -> same catalog/table/index lock. |
| Direct catalog/table/catalog-owned B+ tree | Same engine DatabaseLock; no distinct page/buffer/index mutex. Table scans return materialized snapshots after releasing it. |
| Open / directory ownership | Engine lock -> nonblocking OS lease -> initialization. The losing opener fails before storage opens; cleanup releases partially initialized resources. |
| Shutdown | Engine lock -> catalog/table/index flush/close -> lease release. No independent shutdown mutex or inverse lock order. |
| Raw PageFile / BufferPool / HeapFile / pages | No own synchronization. Supported only single-threaded or inside the enclosing engine operation context. |

Thus supported paths do not acquire independent locks in conflicting table order. This is deadlock prevention by serialization, not detection. DatabaseLock has a 30-second acquisition deadline; HTTP paths translate timeout to 503. Opposite-table-order tests and newly controlled service contention observe actual acquisition attempts, propagate exceptions and bound worker joins. Two processes racing for one directory produce exactly one owner; terminating the idle owner releases the OS lock without deleting the permanent guard file. This tests ownership recovery, not interrupted-write durability.

One process/worker, one engine per local database directory, no waiting for another database worker while holding the lock, and no nesting separate database locks remain deployment constraints. Same-field updates are last completed write wins; there is no optimistic versioning or push synchronization.

## F. Historical hardening-phase test commands and results

These commands ran during the adversarial-hardening phase from the repository root unless explicitly marked frontend. Subsets overlap the full suite and must not be added to its total. They are not the later final P4 acceptance results.

| Check | Command | Result |
| --- | --- | --- |
| Observed backend baseline | .\.venv\Scripts\python.exe -m pytest -q | 718 passed, 7 existing warnings, 83.24s |
| Observed frontend baseline | npm test (frontend) | 66 passed, 14 files, 14.35s |
| Final complete backend | .\.venv\Scripts\python.exe -m pytest -q | 757 passed, 7 existing warnings, 166.92s |
| Final API integration + adversarial | .\.venv\Scripts\python.exe -m pytest -q tests/test_product_api.py tests/test_product_auth.py tests/test_product_authorization.py tests/test_product_membership.py tests/test_adversarial_api.py | 29 passed, 7 existing warnings, 87.42s |
| Final concurrency/guard/service recovery | .\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py tests/test_adversarial_concurrency.py tests/test_adversarial_service.py | 39 passed, 1 existing warning, 15.46s |
| Final storage adversarial | .\.venv\Scripts\python.exe -m pytest tests/test_adversarial_storage.py -q | 12 passed, 10.61s |
| Live HTTP + restart | .\.venv\Scripts\python.exe scripts\smoke_test.py | Passed; real HTTP collaboration, authorization, concurrent writes, index verification and normal restart |
| Final HTTP + restart + Vite | .\.venv\Scripts\python.exe scripts\smoke_test.py --frontend | Passed; all HTTP/restart scenarios plus frontend startup, module serving and authenticated proxy |
| Frontend final | npm test (frontend) | 77 passed, 15 files, 15.84s |
| TypeScript | npm run typecheck (frontend) | Passed |
| Production build | npm run build (frontend) | Passed; 49 modules transformed |
| Diff validation | git diff --check | Passed; only LF/CRLF conversion notices |

Existing warnings concern Starlette/httpx TestClient and per-request cookie deprecations; assertions/dependencies were not weakened to suppress them. Independent suites sometimes ran concurrently on separate temporary databases, so durations are not performance benchmarks.

The first origin-aware Vite smoke failed with 403 at registration. Installed Vite 8.3.3 expands string proxy shorthand to changeOrigin:true; object configuration now explicitly preserves Host. This regression was investigated with the installed source and corrected before final verification. One new validation test initially incorrectly rejected the word password in an error location; the assertion was corrected to reject submitted secret VALUES, while retaining validation/no-mutation assertions.

## G. Regression comparison and test-quality improvements

Backend: 718 -> 757 (+39: nine API, 12 storage, two process/initialization, 16 service/recovery/contention). Existing 20 API cases and 21 concurrency cases are preserved. Frontend: 66 -> 77 (+11), with 15 test files.

New tests compare full logical state/index entries, validate structures, verify no leaked pins, and reopen storage rather than checking only returned status. Membership relocation uses real page capacity. Concurrency tests synchronize at internal operation points and observe the second worker's lock attempt, rather than hoping simultaneous starts overlap. Frontend controlled promises test response order while retaining real providers/UI components; real HTTP/proxy tests cover transport separately. No arbitrary sleeps establish contention; bounded readiness polling in the existing smoke script is distinct.

## H. Files changed in this round

The final authoritative file list is `git status --short`; it includes the inherited implementation, hardening changes, frontend race fixes, new adversarial tests, smoke script and documentation. Incoming implementation changes were preserved using .verification/pre-adversarial.diff and source/test/document copies under .verification/pre-adversarial. These local evidence files are ignored and are not product source or a commit.

## I. Remaining limitations

- One backend worker/engine owner per local directory; coarse serialized throughput and no fairness guarantee.
- No ACID transaction manager, WAL, fsync contract, general statement rollback or arbitrary-crash recovery. Transient-operation compensation requires successful recovery writes; repeated/permanent I/O faults can leave partial state.
- Detached index pages after deletion/failed allocation are retained and counted, not reclaimed. Existing schema/file format remains compatible; no data migration was performed.
- Raw storage access must hold the engine operation context; trusted internal actor_user_id=None and direct SQL/engine access bypass product authorization by design.
- Public SQL console operates on its separate demo database; keep the academic app on controlled local interfaces rather than treating it as an internet-ready service.
- Logical IDs still use MAX+1 and can be reused; token-based logout remains atomic. Concurrent already-authenticated requests can complete while logout occurs. Shared views need refresh and same-field updates are last completed write wins.
- During this hardening phase, no fresh browser visual/interactive acceptance or browser-generated CSRF traffic could be run because no browser was connected. The user-provided successful 12-check acceptance result remained separate from the automated hardening evidence. Later P4 browser and manual evidence is recorded in [verification.md](verification.md).

## J. Repository handling during this phase

Branch: main. HEAD: 04b66c5e54968566062c6083478527aa28c743c3.

No commit, push, reset, discarded user edit, dependency change, or deletion of development/manual-demo data was performed during the hardening phase. Because later phases add further working-tree changes, `git status --short` is the authoritative current file list.

## K. Hardening-phase recommendation

**READY WITH DOCUMENTED LIMITATIONS.** All automated checks requested for this phase passed. This historical verdict remains scoped to the documented single-worker local deployment and does not claim arbitrary-crash recovery, multi-process safety, or a post-hardening visual browser pass. See [verification.md](verification.md) for the final P4 verdict.
