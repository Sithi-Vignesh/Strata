# Strata

For a presentation-ready persistent environment with safe isolated storage, documented demo accounts, collaboration data, SQL examples, and automated readiness checks, see [docs/demo-environment.md](docs/demo-environment.md).

For coordinated release verification across backend, frontend, Chromium, persistence, concurrency, integrity, benchmarks, and optional demo readiness, see [docs/acceptance-testing.md](docs/acceptance-testing.md) or run `python scripts/run_acceptance.py --smoke`.

A collaborative project and task application powered by a custom relational database engine.

Strata combines a Python page-oriented DBMS, a FastAPI backend, and a React/TypeScript frontend. Product data lives in Strata heap files and persistent B+ tree indexes. No external database is used.

## Run and verify

See [the development guide](docs/development.md) for exact Windows startup commands, clean demo directories, and the two-browser acceptance checklist. See [the verification report](docs/verification.md) for the executed checks and implementation log.

From the repository root in PowerShell:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py
cd frontend
npm test
npm run typecheck
npm run build
~~~

The smoke script starts a real loopback HTTP server against temporary databases, uses independent cookie sessions, shuts down normally, and reopens the same files. It does not touch existing development data.

## Application

- Email/password registration, Argon2id hashing, login/logout, and persisted opaque sessions.
- A personal workspace and initial project provisioned at registration.
- Collaborative workspaces with immediate membership by registered email. No invitation delivery or acceptance step.
- OWNER-only membership management, ownership transfer, workspace rename and deletion.
- Projects: create, select, edit and delete empty projects.
- Tasks: create, edit, delete, status, priority, nullable assignment to workspace members, and Kanban status controls.
- Shared notes with author-only editing and deletion.
- Dashboard counts derived from persisted workspace tasks.
- Workspace refresh, selection recovery, and sign-in redirection when a session expires.

Product routes: /login, /register, /, /projects, /tasks and /board. Educational routes /sql and /engine remain separate and publicly accessible in this local demo.

Membership is added with POST /api/workspaces/{id}/members and a body containing only an email. Addresses are trimmed and case-folded like registration. Unknown addresses return 404; duplicate/inactive memberships return 409; malformed requests return 422. Non-members cannot inspect workspace resources. Removing a member unassigns their tasks and retains historical authorship. Exactly one OWNER is preserved during ownership transfer.

## Engine capabilities

- 4096-byte pages, slotted records, heap files, typed tuple serialization and persistent catalog metadata.
- Bounded buffer pools with CLOCK replacement, pin/unpin bookkeeping and dirty-page writeback.
- Persistent B+ tree secondary indexes, backfill, point/range access, and insert/update/delete maintenance.
- Handwritten SQL lexer, recursive-descent parser, immutable AST and semantic binder.
- Deterministic rule-based planning and Volcano-style open/next/close execution.
- Filtering, projection, sorting, LIMIT/OFFSET, global/grouped aggregation and one two-table equality INNER JOIN.
- Profiling of logical table/index scan work, including tree pages visited, entries examined, selected RIDs and fetched rows. These are not disk-I/O measurements or optimizer cost estimates.
- Coordinated database operation locking with a reproducible deadlock-prevention experiment.

The engineering contribution is implementing and connecting these established database techniques to a real multi-user application, not claiming the techniques themselves are novel.

### SQL scope

Supported statements are CREATE TABLE, DROP TABLE, one-row literal INSERT, SELECT, literal-assignment UPDATE and DELETE. SELECT supports comparisons, AND/OR/NOT, NULL predicates, ORDER BY, LIMIT/OFFSET, COUNT/SUM/AVG/MIN/MAX, GROUP BY, and the constrained join above. The planner can use an eligible indexed comparison while retaining the full filter for correctness.

~~~sql
CREATE TABLE example (id INTEGER, title VARCHAR(64), active BOOLEAN);
INSERT INTO example VALUES (1, 'Design the schema', TRUE);
SELECT id, title FROM example WHERE active = TRUE ORDER BY id LIMIT 20;
UPDATE example SET title = 'Finalize schema' WHERE id = 1;
DELETE FROM example WHERE id = 1;
~~~

Indexes are created through the engine API, not SQL DDL. Indexed types are INTEGER, BIGINT, BOOLEAN and VARCHAR; NULL keys are omitted and FLOAT indexing is unsupported. UPDATE/DELETE materialize their target RIDs before mutation. Updates preserve a RID when the replacement fits, relocate otherwise, and maintain attached indexes with best-effort row-local compensation.

## Architecture and concurrency

~~~text
React -> FastAPI authentication -> ProductService authorization/integrity
      -> shared database operation lock -> Catalog / Table / B+ tree
      -> HeapFile / buffer pools / slotted pages / page files
~~~

One reentrant lock belongs to each engine and is passed to its catalog, tables, indexes, services and adapter. Product operations hold it across authorization, ID allocation and mutation; SQL holds it through binding, execution and materialization. This prevents conflicting table-lock orders because there are no separate table/page locks on these paths. Acquisition times out after 30 seconds; HTTP callers receive 503 and may retry.

One open catalog owns each local database directory. An OS file-lock guard rejects additional engine instances and backend workers before they open the catalog. This is exclusive ownership, not support for cooperating multi-process writers. Use one backend worker on local disk. Raw HeapFile/BufferPool/Page APIs and manually assembled operators require an enclosing engine.operation() context; standalone raw storage objects are single-threaded.

Do not nest locks from different engines, await, or wait for another database worker while holding an operation lock. Normal application paths never do so. There is no transaction manager, 2PL, MVCC, automatic rollback, WAL or arbitrary-crash recovery. Serialization reduces throughput and does not resolve last-writer-wins edits to the same field.

Details: [architecture](docs/architecture.md), [storage](docs/storage.md).

## Persistence and separation

The product database defaults to data/strata; the independent SQL demonstration database defaults to data/dbthon_demo. STRATA_PRODUCT_DATA_DIR and STRATA_DATA_DIR override these separately. Never point both at the same directory. Startup validates/creates schemas and indexes; a fresh product database includes the historical development seed. Its seed user has no password; register your own accounts.

Normal shutdown flushes dirty buffers and index metadata. Data and live sessions survive a normal restart. Multi-step failures can leave partial mutations; existing registration/membership and row-update compensation is best effort. Back up only after stopping the backend. There are no schema migration tools: preserve older incompatible databases and use a different demo directory, rather than deleting them.

## Known limits

- Educational SQL subset; no cost-based optimizer, general joins/subqueries, native foreign keys or uniqueness constraints.
- Product integrity and permissions are enforced by ProductService; direct engine code is trusted and can bypass application rules.
- Index deletion does not provide full rebalancing or reclaim disk pages.
- Task deletion removes notes first; non-empty projects/workspaces cannot be deleted. Unexpected I/O failures in multi-step deletes can leave partial results.
- No real-time push: use Refresh workspace or reload. Same-field concurrent edits use the last completed write.
- Local demonstration deployment only. The SQL console deliberately permits mutations to its separate demo database and is unauthenticated.
- Human browser acceptance is a separate gate; automated checks do not complete it.

No changes are committed or pushed automatically.
