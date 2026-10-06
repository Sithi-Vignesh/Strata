# Strata

> **Strata: A Collaborative Project Management System Powered by a Relational Database Engine Built from Scratch**

Strata is a database-systems project in which a realistic project-management application is the workload and the custom relational DBMS is the technical innovation. It consists of a relational engine written from scratch in Python, a FastAPI bridge that exposes the engine to the application, a React/TypeScript frontend under active development, and a deterministic DBthon task-management demo workload. It uses no external database engine or ORM.

## Status

The database and backend foundation required for the DBthon demo is complete and frozen. The completed milestones include rule-based index-aware execution (Phase 21A), query execution profiling (Phase 21B.1), and the FastAPI DBthon bridge with deterministic demo bootstrap (Phase 21B.2).

UI-1, the completed frontend foundation, provides React, TypeScript, Vite, Tailwind CSS v4, routing, typed API integration, a development proxy, backend health connectivity, and focused tests. Its routes are intentionally placeholder surfaces; the polished product experience and execution visualizations are later UI work.

### Completed phase history

| Phase | Delivered capability |
| --- | --- |
| 0 - Repository Foundation | Source layout, `StrataEngine`, backend adapter, and FastAPI health check. |
| 1 - Core Storage | Fixed-size pages, `PageId`, and disk-backed page-file I/O. |
| 2 - Record IDs and Slotted Pages | Stable `RecordId` values, slotted-page records, deletion, and compaction. |
| 3 - Buffer Pool Manager | Bounded in-memory page cache, pin tracking, dirty write-back, and CLOCK replacement. |
| 4 - Heap File | Multi-page, variable-length record storage over slotted pages. |
| 5 - Schema, Tuple Serialization, Catalog, and Table | Typed relational rows, persistent metadata, and table operations. |
| 6 - Query Execution | Volcano-style `TableScan`, `Filter`, and `Projection` operators. |
| 7 - Query Planning | Immutable reusable plan trees that construct fresh operator trees. |
| 8 - Minimal SQL SELECT Frontend + Binding | Read-only SQL syntax, parsing, and binding to query intent. |
| 9 - Compound Predicate Expressions | `AND`, `OR`, `NOT`, parentheses, and conventional precedence. |
| 10 - ORDER BY + LIMIT/OFFSET | Stable in-memory ordering and streaming pagination. |
| 11 - Global Aggregation | `COUNT`, `SUM`, `AVG`, `MIN`, and `MAX`. |
| 12 - Two-table INNER JOIN | One equality join with qualified references, filtering, ordering, and pagination. |
| 13 - GROUP BY / Grouped Aggregation | Grouped aggregation, output ordering, and pagination. |
| 14 - Two-table INNER JOIN + Aggregation | Global and grouped aggregation over one equality join. |
| 15 - Engine SQL Integration | Public `StrataEngine.execute()` returning materialized `QueryResult` values. |
| 16 - Minimal SQL INSERT | One ordered literal row through the typed table path. |
| 17 - Minimal SQL CREATE TABLE | Persistent table creation through SQL. |
| 18 - Minimal SQL DROP TABLE | Persistent table deletion through SQL. |
| 19 - Persistent B+ Tree Core | Durable typed B+ trees, splits, leaf links, range scans, and traversal metrics. |
| 20 - Index Lifecycle & Table Integration | Catalog-backed single-column indexes, backfill, row-level maintenance, reopen, and table-drop cleanup. |
| 21A - Index-Aware Query Execution | Rule-based selection of `IndexScan` for eligible single-table predicates. |
| 21B.1 - Query Execution Profiling | Actual scan-work instrumentation through `execute_profiled()`. |
| 21B.2 - DBthon FastAPI Bridge | Profile API, deterministic task bootstrap, CORS, and safe health endpoint. |
| UI-1 - Frontend Foundation & Backend Integration | React/Vite foundation, routing, typed client, Vite proxy, health check, and frontend tests. |

## Current architecture

```text
React / TypeScript Frontend
        |
        | HTTP
        v
FastAPI
        |
        v
EngineAdapter
        |
        v
StrataEngine
        |
        v
SQL Lexer / Parser
        |
        v
Binder
        |
        v
Planner
        |
        v
Execution Operators
        |
        v
Schema / Catalog / Table
        |
        v
Heap / Buffer Pool
        |
        v
Pages / Records
        |
        v
Disk
```

SQL AST nodes are syntax-oriented and unresolved. The Binder resolves SQL against the catalog, the Planner creates physical plans, and execution remains independent of SQL and planning. Storage knows nothing about SQL. FastAPI uses the public engine boundary through `EngineAdapter`, and the frontend interacts with the backend through HTTP only.

## Index-aware execution

Strata has catalog-backed, persistent, single-column, non-unique B+ tree indexes. Supported index key types are `INTEGER`, `BIGINT`, `BOOLEAN`, and `VARCHAR`; `FLOAT` index keys are unsupported. Existing rows are backfilled, `NULL` keys are skipped, inserts and deletes maintain index entries, metadata and files survive reopen, and dropping a table removes its owned index files.

The planner now performs **rule-based index-aware planning** for eligible single-table comparisons: `=`, `<`, `<=`, `>`, and `>=`. It deterministically chooses an eligible index and retains the original filter above `IndexScan` for correctness. Non-eligible predicates fall back to `TableScan`; joins continue to use `TableScan` inputs.

This is not a cost-based optimizer. There is currently no multi-index intersection, index-only scan, index nested-loop join, or `ORDER BY` elimination through index ordering. SQL `CREATE INDEX` and `DROP INDEX` are not implemented.

## Query execution profiling

`StrataEngine.execute_profiled()` runs supported SQL once and returns ordinary query or command output together with an optional **Execution Profile**. `execute()` retains its normal semantics.

Profiles describe actual executed scan work, not optimizer cost estimates, benchmark timings, or page-I/O accounting:

| Access path | Metrics |
| --- | --- |
| `TableScan` | `tuples_examined` |
| `IndexScan` | `tree_pages_visited`, `leaf_entries_examined`, `rids_selected`, `rows_fetched` |

Candidate/index work can differ from the final returned-row count, and `LIMIT` can stop operator consumption early. Commands return `profile: null`. Joined queries also return `profile: null` rather than implying a misleading single access path. This capability is execution profiling, not SQL `EXPLAIN`.

## DBthon FastAPI bridge

The FastAPI application owns engine lifecycle, bootstraps the demo dataset on startup, and reaches the database only through `EngineAdapter`.

- `GET /health` returns safe service and engine status fields.
- `POST /api/sql/profile` accepts one SQL statement:

```json
{ "sql": "SELECT id FROM tasks WHERE status = 'BLOCKED'" }
```

A query response includes `kind`, `columns`, `rows`, `row_count`, and `profile`. A command response includes `kind`, `affected_rows`, and `"profile": null`. Client SQL/domain errors are returned as structured HTTP 400 responses; unexpected server failures use a safe HTTP 500 response.

`STRATA_DATA_DIR` overrides the backend data directory (default: `data/dbthon_demo`). `STRATA_FRONTEND_ORIGIN` overrides the allowed frontend origin (default: `http://localhost:5173`). Frontend development normally uses the Vite proxy, so browser code calls relative `/health` and `/api/...` paths.

## Deterministic DBthon dataset

Bootstrap creates the `tasks` table with 1,000 deterministic rows and ensures the required `tasks_status_idx` index on `tasks.status`. It is reopen-safe: an existing demo database is reused and the required index is checked.

| Column | Type |
| --- | --- |
| `id` | `INTEGER NOT NULL` |
| `title` | `VARCHAR(96) NOT NULL` |
| `status` | `VARCHAR(16) NOT NULL` |
| `priority` | `VARCHAR(16) NOT NULL` |
| `assignee` | `VARCHAR(32) NULL` |
| `project` | `VARCHAR(32) NOT NULL` |

Status distribution: `TODO`, `IN_PROGRESS`, `REVIEW`, `BLOCKED`, and `DONE` each have 200 rows. Priority distribution: `LOW`, `URGENT`, `HIGH`, and `MEDIUM` each have 250 rows.

### TableScan and IndexScan demonstration

The canonical unindexed demonstration query is:

```sql
SELECT id, title, status, priority
FROM tasks
WHERE priority = 'URGENT';
```

It returns 250 rows and uses `TableScan`; when fully consumed, it examines 1,000 tuples.

The canonical indexed demonstration query is:

```sql
SELECT id, title, status, priority
FROM tasks
WHERE status = 'BLOCKED';
```

It returns 200 rows and uses `IndexScan` through `tasks_status_idx`. The API and future UI expose current execution metrics at runtime; the README does not hardcode B+ tree traversal values or claim benchmark speedups.

## Current SQL capability

The SQL frontend supports a deliberately narrow subset:

- single-table `SELECT` with `*` or explicit projection;
- `WHERE` with comparisons, `AND`, `OR`, `NOT`, parentheses, `IS NULL`, and `IS NOT NULL`;
- eligible indexed single-table predicates using `IndexScan`;
- source-column `ORDER BY` with ASC/DESC and multiple items;
- `LIMIT` and `LIMIT ... OFFSET ...`;
- global aggregates: `COUNT(*)`, `COUNT(column)`, `SUM`, `AVG`, `MIN`, `MAX`;
- single-table `GROUP BY`, including mixed grouping/aggregate output and post-aggregate ordering;
- exactly one two-table equality `JOIN` / `INNER JOIN`, including joined filtering, ordering, pagination, and global/grouped aggregation;
- constrained one-row literal `INSERT`, minimal `CREATE TABLE`, and `DROP TABLE`.

For grouped queries, `WHERE` runs before aggregation, while `ORDER BY` and `LIMIT`/`OFFSET` run afterward. Ordinary selected columns must appear in `GROUP BY`; `GROUP BY` without aggregates is unsupported. `INSERT` accepts exactly one literal row in schema order and returns `CommandResult(affected_rows=1)`. SQL-created columns are non-nullable.

## Frontend UI-1 foundation

The `frontend/` application uses React, TypeScript, Vite, Tailwind CSS v4, and React Router. UI-1 establishes a typed backend API contract, a typed `fetch` client, Vite development proxying, a small backend-health indicator, and frontend tests.

Current routes are foundation/placeholder surfaces:

```text
/
/tasks
/board
/sql
/engine
```

Later UI phases will implement the product-management experience, SQL console, execution-profile presentation, and engine visualizations.

## Repository structure

```text
Strata/
|- frontend/
|  |- src/
|  |  |- api/             # typed backend client
|  |  |- app/             # router and application entry
|  |  |- components/      # shared layout
|  |  |- pages/           # current placeholder route surfaces
|  |  `- types/           # API contract types
|  |- package.json
|  `- vite.config.ts
|- src/
|  |- strata_engine/      # custom relational engine
|  `- strata_backend/     # FastAPI and EngineAdapter bridge
|- tests/                 # Python engine/backend coverage
|- docs/
|- data/                  # runtime data directory
`- pyproject.toml
```

## Quick start

Strata requires Python 3.10 or newer. From the repository root:

```bash
python -m venv .venv
```

Activate the environment. On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then install the project and development dependencies and run the Python tests:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Start the backend in one terminal:

```bash
python -m uvicorn strata_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite serves the frontend at `http://localhost:5173` and proxies `/health` and `/api/...` to the backend at `http://127.0.0.1:8000`.

Useful frontend validation commands:

```bash
npm run typecheck
npm run test
npm run build
```

## Validation and quality

Authoritative Python/backend validation on Python 3.12.10 reports **585 passed**, **0 failed**, and **1 known third-party deprecation warning** (`StarletteDeprecationWarning` involving FastAPI `TestClient` / httpx).

Frontend UI-1 validation on Node 22.14.0 and npm 10.9.2 reports:

- 2 frontend test files / 6 tests passed;
- `npm run typecheck` passed;
- `npm run test` passed;
- `npm run build` passed;
- `npm ls` produced a valid dependency tree.

The Python and frontend totals are separate validation baselines.

## DBthon direction

The application is the workload; the custom DBMS is the innovation. The intended DBthon flow establishes Strata as a project-management application, shows its task workload, reveals the custom relational engine underneath, runs SQL against that workload, compares TableScan and IndexScan execution profiles, and exposes B+ tree instrumentation. The frontend visualization for this flow is not complete in UI-1.

## Not yet implemented

- cost-based or statistics-driven optimization;
- SQL `CREATE INDEX` / `DROP INDEX`;
- multi-index intersection, index-only scans, index nested-loop joins, or `ORDER BY` elimination through index ordering;
- `HAVING`, aliases, `DISTINCT`, subqueries, or broader scalar expressions;
- multiple/chained joins, outer joins, or non-equality joins;
- transactions, concurrency control, locking/deadlock handling, WAL, or recovery;
- a broad production CRUD API, authentication, comments, notifications, or realtime collaboration;
- polished product-management UI and DBthon execution visualizations.

## Historical notes

Phase 5 introduced typed relational data, immutable schemas, binary tuple serialization, persistent catalog metadata, and tables. Phase 6 introduced the Volcano operator lifecycle; joins, aggregates, sorting, SQL parsing, and pagination arrived in later phases. Phase 7 introduced immutable reusable plan trees; current plans cover scans, filters, projections, sorting, limits, aggregation, joins, and index scans.
