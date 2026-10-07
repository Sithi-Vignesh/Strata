# Strata

> A collaborative project-management system powered by a relational database engine built from scratch.

Strata combines a custom persistent relational engine in Python with a FastAPI bridge and a React/TypeScript interface. The engine is substantial infrastructure and a major technical foundation; the long-term product is a collaborative workspace for projects, tasks, and notes.

Today, Strata provides a working engine, deterministic DBthon demo, SQL/profile interface, and an isolated mutable product REST API. It is not yet a complete collaborative product.

## Project status

Current capabilities include:

- a custom page-backed relational engine with typed tuples, a persistent catalog, and B+ tree secondary indexes;
- a constrained SQL frontend supporting `CREATE TABLE`, `DROP TABLE`, `INSERT`, `SELECT`, `UPDATE`, and `DELETE`;
- FastAPI integration, including SQL execution profiling;
- a React demo interface for overview, task, board, SQL-console, and engine-explanation views.
- a six-table product schema, deterministic development seed, persistent product indexes, create/read/update/delete `ProductService` lifecycle, and REST API.

The current frontend pages use real engine data, but they are primarily demo/read-oriented. Authentication, richer multi-user workflows, and collaboration are future work; the frontend has not yet switched to the product API.

## Why Strata

Strata is built around a practical constraint: the application should determine what the database needs next. The project-management workload drives the engine roadmap instead of treating database features as isolated exercises.

## Architecture

### Product path

```text
FastAPI product routes
  -> ProductService
  -> application integrity and business rules
  -> Strata Table APIs
  -> custom relational engine and storage
```

The current product flow is `User -> Workspace membership -> Workspace -> Projects -> Tasks -> Notes`. Task assignees are nullable; a non-null assignee and a note author must belong to the task project's workspace.

`ProductService` serializes each public operation with one process-local service-instance lock. This is not a database transaction, rollback mechanism, ACID guarantee, 2PL, MVCC, or crash-recovery mechanism.

The initial deletion rules are intentionally explicit: deleting a task removes its notes first; deleting a project is rejected while tasks exist; deleting a workspace is rejected while projects exist and otherwise removes workspace memberships first. Those multi-row operations are process-serialized but not transactionally atomic.

### SELECT path

```text
SQL text
  -> Lexer
  -> Parser
  -> unresolved immutable AST
  -> Binder
  -> QueryRequest
  -> deterministic Planner
  -> Physical Plan
  -> Volcano-style execution operators
  -> QueryResult
```

### Mutation path

```text
UPDATE / DELETE
  -> Lexer / Parser / AST
  -> Binder
  -> mutation command
  -> MutationTargetScan
  -> RID-aware fixed target snapshot
  -> Table mutation
  -> heap and index maintenance
```

`SELECT` uses the planner. `UPDATE` and `DELETE` deliberately use a table-scan mutation target snapshot rather than normal query planning, so target selection completes before mutation begins.

## Database engine

### SQL frontend and commands

The engine has a handwritten lexer, recursive-descent parser, immutable unresolved AST, and binder/semantic-resolution layer. Identifiers are case-insensitive. The supported statement families are deliberately narrow:

- `CREATE TABLE` and `DROP TABLE`;
- one-row, literal `INSERT` in schema order;
- `SELECT`;
- `UPDATE` with literal assignments;
- `DELETE`.

This is not a general SQL implementation. SQL `CREATE INDEX` and `DROP INDEX` are not available; indexes are created through the engine API.

### Query planning and execution

The planner is deterministic and rule-based, not cost-based. It has no statistics, cardinality estimation, cost model, adaptive behavior, or sophisticated join ordering.

Execution uses a Volcano-style `open()`, `next()`, `close()` lifecycle. Current operators include `TableScan`, `IndexScan`, `Filter`, `Projection`, `Sort`, `Limit`, `Aggregate`, `NestedLoopJoin`, and `JoinProjection`.

For eligible single-table comparisons (`=`, `<`, `<=`, `>`, `>=`), the planner may select the first eligible indexed comparison in a left-to-right `AND` traversal and retain the complete filter for correctness. `OR`, `NOT`, NULL tests, unindexed predicates, and joins remain table-scan paths. Joins are limited to exactly two tables and an equality `JOIN`/`INNER JOIN`; they use nested loops.

### SELECT capabilities

`SELECT` supports:

- `*` or explicit projection;
- comparisons, `AND`, `OR`, `NOT`, parentheses, `IS NULL`, and `IS NOT NULL` predicates;
- `ORDER BY` with ASC/DESC, `LIMIT`, and `OFFSET`;
- global and grouped aggregation: `COUNT`, `SUM`, `AVG`, `MIN`, and `MAX`;
- `GROUP BY` with the engine's aggregate restrictions;
- one equality two-table `JOIN` / `INNER JOIN`.

### Storage

The storage subsystem provides persistent, page-backed storage with 4096-byte pages, disk page files, a bounded buffer pool with CLOCK replacement, slotted pages, heap files, `RecordId` (RID) addressing, typed tuple serialization, and persistent catalog metadata.

`SlottedPage.update_record(...)` and `HeapFile.update_record(...)` provide same-page physical replacement. A successful replacement preserves the slot/RID, supports shrinking or growing records where capacity permits, and rebuilds/compacts the page while preserving live slot IDs. If the source page cannot hold the replacement, it fails atomically with `InsufficientSpaceError`.

At the relational layer, `Table.update(record_id, row) -> RecordId` validates the replacement, first attempts same-page replacement, and relocates only when the source page lacks capacity. It returns the final live RID, maintains all attached indexes (including NULL transitions and multiple indexes), and performs best-effort row-local compensation when a row update fails. This is not transactional statement processing.

### Indexing

Strata has persistent, page-backed B+ tree secondary indexes integrated with catalog metadata. Existing rows are backfilled; `INSERT`, `UPDATE`, and `DELETE` maintain index entries; and index files and metadata survive reopening the database.

Supported indexed key types are `INTEGER`, `BIGINT`, `BOOLEAN`, and `VARCHAR`. `FLOAT` indexing is unsupported and NULL keys are skipped. The tree supports point and range access for `IndexScan`, but does not currently provide full delete rebalancing/page reclamation, index-only scans, multi-index intersection, index nested-loop joins, or `ORDER BY` elimination through index ordering.

### Mutations

`DELETE` supports:

```sql
DELETE FROM table_name [WHERE predicate];
```

Its path is `DeleteStatement -> Binder -> DeleteCommand -> MutationTargetScan -> fixed RID-aware target snapshot -> Table.delete()`.

`UPDATE` supports literal-only assignments:

```sql
UPDATE table_name
SET column_name = literal [, column_name = literal ...]
[WHERE predicate];
```

Supported assignment literals are integers, floats, strings, `TRUE`, `FALSE`, and `NULL`. The path is `UpdateStatement -> Binder -> UpdateCommand -> MutationTargetScan -> fixed RID-aware snapshot -> prebuild and validate every replacement tuple -> Table.update()`.

`UPDATE` does not support expressions, column-reference RHS values, arithmetic, functions, subqueries, `UPDATE FROM`, joins, `RETURNING`, `ORDER BY`, or `LIMIT`. Assignment targets are resolved once by the binder, duplicate targets are rejected case-insensitively, and all replacement rows are built and validated before the first target row changes. SQL never manipulates B+ trees directly; index behavior belongs to `Table.update()`.

### Profiling

`StrataEngine.execute_profiled(...)` runs a statement once and returns its ordinary result plus an optional observational query profile. Normal `execute()` behavior is unchanged.

Profiles report actual logical scan work, not `EXPLAIN`, cost estimates, disk I/O, page-read counts, or timing benchmarks:

| Access path | Metrics |
| --- | --- |
| `TableScan` | `tuples_examined` |
| `IndexScan` | `tree_pages_visited`, `leaf_entries_examined`, `rids_selected`, `rows_fetched` |

Command statements (`INSERT`, `UPDATE`, `DELETE`, and DDL) naturally return no query scan profile. Joined queries also have no single-path profile.

## Supported SQL examples

```sql
CREATE TABLE example (
  id INTEGER,
  title VARCHAR(64),
  active BOOLEAN
);

INSERT INTO example VALUES (1, 'Design the schema', TRUE);

SELECT id, title
FROM example
WHERE active = TRUE
ORDER BY id ASC
LIMIT 20;

UPDATE example
SET title = 'Finalize schema', active = FALSE
WHERE id = 1;

DELETE FROM example
WHERE id = 1;

SELECT status, COUNT(*)
FROM tasks
GROUP BY status
ORDER BY status ASC;

SELECT tasks.id, projects.name
FROM tasks
INNER JOIN projects ON tasks.project_id = projects.id
WHERE tasks.id = 42;
```

The examples demonstrate accepted syntax, not broader SQL compatibility. SQL-created columns are non-nullable; `VARCHAR` declarations require a length.

## Backend and demo database

The FastAPI application owns two separate engine lifecycles. The DBthon demo engine is accessed through `EngineAdapter`, which serializes one profiled execution at a time. The adapter lock is not a transaction system. The product engine is bootstrapped independently and serves a lifespan-owned `ProductService`.

Available endpoints:

- `GET /health` — service and engine status;
- `POST /api/sql/profile` — execute one supported SQL statement and return result data plus an optional profile.

The application starts with a deterministic demo database at `data/dbthon_demo` by default. `STRATA_DATA_DIR` can override its directory. The product database defaults to `data/strata` and `STRATA_PRODUCT_DATA_DIR` can override it. `STRATA_FRONTEND_ORIGIN` configures the allowed frontend origin; CORS permits `GET`, `POST`, `PATCH`, and `DELETE` for that origin.

Bootstrap creates/reuses a `tasks` table with 1,000 deterministic task rows and ensures `tasks_status_idx` on `tasks.status`. It is a reproducible workload for the frontend and SQL/profile demonstrations, not the future production workspace schema.

### Product foundation and demo separation

`src/strata_backend/product_bootstrap.py` owns the product structural initializer. `initialize_product(engine)` creates or validates product tables and indexes without changing existing rows. `bootstrap_product(engine)` adds the deterministic development seed only when every product table is empty.

The product schema contains users, workspaces, workspace memberships, projects, tasks, and notes. Its persistent single-column indexes cover email, memberships, project workspace IDs, task project/assignee IDs, and note task IDs. These indexes are non-unique; `ProductService` enforces logical-ID, email, membership, and relationship rules at the application layer.

The mutable product foundation remains separate from `data/dbthon_demo`, `demo_bootstrap.py`, and the current DBthon SQL/profile frontend flow because both layers own incompatible `tasks` schemas.

Product routes are available under `/api`: users and their workspaces, workspaces and members, nested projects, nested tasks, and nested notes, plus individual read/update/delete routes. Request and response payloads use logical IDs only; engine record identifiers and storage metadata are not exposed. Authentication is not part of this phase, so workspace ownership and note authorship use explicit user IDs. Product deletion rules remain the `ProductService` rules: task deletion removes notes, while non-empty projects and workspaces cannot be deleted.

Start the backend from the repository root:

```bash
python -m uvicorn strata_backend.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend

`frontend/` uses React, TypeScript, Vite, Tailwind CSS, and React Router. Current routes are:

| Route | Current behavior |
| --- | --- |
| `/` | SQL-backed task-status overview. |
| `/tasks` | SQL-backed deterministic task table. |
| `/board` | SQL-backed board grouped by status. |
| `/sql` | Connected SQL Console with result rendering and execution profiles. |
| `/engine` | Explanatory/static engine architecture page. |

The frontend is not yet a full collaborative application: it has no authentication, workspace creation, project/task editing, assignments, notes CRUD, or real-time collaboration wired to the product API.

## Repository structure

```text
Strata/
|- frontend/              # React/Vite demo interface
|- src/
|  |- strata_engine/      # custom relational engine
|  `- strata_backend/     # FastAPI and EngineAdapter bridge
|- tests/                 # Python engine/backend coverage
|- docs/                  # deeper architecture and storage notes
|- data/                  # runtime database directory
`- pyproject.toml
```

## Running locally

Strata requires Python 3.10 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
```

On Windows PowerShell, activate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start the frontend separately:

```bash
cd frontend
npm install
npm run dev
```

Vite serves `http://localhost:5173` and proxies `/health` and `/api/...` to the backend. Useful frontend checks are `npm run typecheck`, `npm run test`, and `npm run build`.

## Testing

Run the Python suite with:

```bash
python -m pytest -q
```

The B1 checkpoint previously verified **653 tests passing**, with one known Starlette/httpx `TestClient` deprecation warning. Run the suite after changes rather than treating that historical count as a current guarantee.

## Current limitations

- SQL is intentionally constrained: one-row `VALUES`-only `INSERT`, literal-only `UPDATE` RHS, no `ALTER TABLE`, no SQL index DDL, no subqueries, aliases, `DISTINCT`, `HAVING`, or broad scalar expressions.
- JOINs are exactly two-table equality inner joins; there are no outer joins, chained joins, hash joins, or merge joins.
- Mutation target selection is currently table-scan based, even when an indexed predicate is available.
- There is no transaction manager, statement rollback, `BEGIN`/`COMMIT`/`ROLLBACK`, locks/2PL, MVCC, deadlock detection, WAL, or crash recovery. An unexpected multi-row mutation failure can leave earlier rows modified.
- Planning is rule-based, not cost-based; there are no statistics or advanced join optimization.
- B+ tree indexing has the restrictions described above, including no index-only scans or multi-index intersection.
- There are no PK, FK, UNIQUE, CHECK, auto-increment, or sequence features; product integrity is currently application-enforced.
- There is no authentication, session management, or product authorization beyond the existing workspace-membership rules. The frontend still uses the DBthon demo integration rather than the product API.

## Roadmap

The application determines which DBMS work matters next.

1. **Phase A — application-critical SQL:** `SELECT` / `INSERT` / `UPDATE` / `DELETE` foundation complete.
2. **Phase B1:** six-table product schema, deterministic development seed, and persistent product indexes complete.
3. **Phase B2A:** create/read `ProductService`, application integrity validation, and process-local service serialization complete.
4. **Phase B2B:** update and deletion lifecycle complete.
5. **Phase B3:** product REST API/lifecycle integration complete.
6. **Next:** product frontend workflow integration.
7. **Later full version:** authentication/session security, richer roles/permissions, timestamps/deadlines, invitations/member management, activity/notifications, richer task features, and justified real-time collaboration.
8. **Later engine work driven by product needs:** constraints, stronger ID generation, transactions/concurrency control, locking/2PL/deadlock handling, WAL/recovery, and optimizer improvements.

## Demo reset

The demo database is `data/dbthon_demo`. Restarting the backend reuses it. To reset it, stop the backend, delete that directory, and restart the backend so bootstrap recreates the deterministic dataset and status index. This is destructive.
