# Strata

> **Collaborative project and task-management application intended to be powered by a custom relational database engine written from scratch in Python.**

Strata is a CSE302L / BCSE302P Database Systems project built bottom-up: first the database engine, then the application-domain backend and frontend. It uses no external database engine or ORM.

## Status

**Phase 8 — Minimal SQL SELECT Frontend + Binding is implemented.** It adds a deliberately narrow SQL lexer, parser, unresolved immutable AST, and Binder over the existing planning and execution layers.

Before Phase 8, the suite had **291 passing tests** across storage, buffer pooling, heap files, schema and serialization, catalog and tables, query execution, query planning, and engine/backend integration. Two third-party dependency deprecation warnings are known and are not project test failures.

### Completed phase history

| Phase | Delivered capability |
| --- | --- |
| 0 — Repository Foundation | Source layout, StrataEngine, backend adapter, and FastAPI health check. |
| 1 — Core Storage | Fixed-size pages, PageId, and disk-backed page-file I/O. |
| 2 — Record IDs and Slotted Pages | Stable RecordIds, slotted-page records, deletion, and compaction. |
| 3 — Buffer Pool Manager | Bounded in-memory page cache, pin tracking, dirty write-back, and CLOCK replacement. |
| 4 — Heap File | Multi-page, variable-length record storage over slotted pages. |
| 5 — Schema, Tuple Serialization, Catalog, and Table | Typed relational rows, persistent metadata, and table operations. |
| 6 — Query Execution | Volcano-style TableScan, Filter, and Projection operators. |
| 7 — Query Planning | Immutable reusable plan trees that construct fresh Phase 6 operator trees. |
| 8 — Minimal SQL SELECT Frontend + Binding | A single-table read-only SQL frontend that binds to existing QueryRequest, Planner, and operators. |

## Architecture

The engine layers remain deliberately one-directional:

~~~text
Planning
    ↓
Execution
    ↓
Schema / Catalog
    ↓
Storage
~~~

Planning may depend on execution; execution must not depend on planning. The backend communicates with the public engine API through EngineAdapter and does not manipulate storage internals.

## Phase 5: relational schema, serialization, catalog, and tables

Phase 5 turns opaque heap-file records into typed relational data.

- **DataType** supports INTEGER, BIGINT, FLOAT, BOOLEAN, and VARCHAR.
- **Column** provides immutable definitions with identifier validation, nullability, and VARCHAR length rules.
- **Schema** supports 1–256 columns, preserves column names, resolves names case-insensitively, rejects case-insensitive duplicates, and computes a deterministic fingerprint.
- **Tuple and TupleSerializer** provide immutable schema-bound rows; strict runtime type validation; a null bitmap; big-endian binary serialization; UTF-8 VARCHAR; schema-fingerprint checking; a maximum serialized tuple size of 4084 bytes; and corruption or schema-mismatch detection.
- **Catalog and Table** persist metadata in catalog/tables.db and catalog/columns.db, store each table in its own file, allocate monotonic high-water-mark table IDs without reuse, reconcile orphan table files, and provide create_table, get_table, has_table, drop_table, and list_tables.
- **Table** offers typed insert, get, delete, scan, and count operations with explicit lifecycle management.

## Phase 6: query execution

The execution package implements a streaming Volcano-style pipeline:

~~~text
Table
  ↓
TableScan
  ↓
Filter
  ↓
Projection
~~~

Operator instances follow an explicit lifecycle:

~~~text
UNINITIALIZED
  → open() → ACTIVE
  → EOF → EXHAUSTED
  → close() → CLOSED
~~~

- Calling next() before open() or after close() is invalid.
- EOF returns None repeatedly.
- close() is idempotent; failures clean up while preserving the original exception.
- Iterator use opens and closes an operator only when it owns that lifecycle.
- Projection owns its child (such as Filter); Filter owns its child (such as TableScan); TableScan borrows its Table. Closing operators never closes the underlying Table.

### Predicates and projection

- ComparisonPredicate supports =, ==, !=, <>, <, <=, >, and >=; == normalizes to =.
- Ordinary comparisons against NULL do not match. IsNullPredicate supplies explicit IS NULL and IS NOT NULL behavior.
- Projection accepts 1–256 columns, resolves names case-insensitively, rejects duplicate names, preserves the requested order, and emits fresh output Tuple objects.

Phase 6 deliberately does not implement joins, aggregates, sorting, GROUP BY, DISTINCT, LIMIT/OFFSET, SQL parsing, optimization, indexes, mutation operators, or transactions.

## Phase 7: query planning

The planning package converts already-resolved query intent into reusable descriptions of Phase 6 execution trees:

~~~text
Resolved query intent
  ↓
QueryRequest
  ↓
Planner
  ↓
Plan tree
  ↓
Phase 6 operator tree
  ↓
Table
  ↓
Storage
~~~

Plans describe execution but do not execute it. They expose schema, are structurally immutable after construction, and each create_operator() call produces a fresh unopened operator tree.

- **TableScanPlan** wraps a resolved Table, exposes exactly table.schema, borrows the table, and creates a fresh TableScan.
- **FilterPlan** wraps a child Plan and an existing Phase 6 Predicate. It validates the predicate during construction, preserves child-schema identity, and creates a Filter around a fresh child operator tree.
- **ProjectionPlan** wraps a child plan and 1–256 projected columns. It validates case-insensitive resolution, duplicate and missing columns during construction; preserves requested order; creates a new output Schema that reuses existing Column definitions; and creates a Projection around a fresh child operator tree.
- **QueryRequest** holds a resolved Table, optional existing Predicate, and optional projection. It is immutable, normalizes projection sequences to tuples, distinguishes None (no projection) from an explicitly empty projection, and rejects the latter when planned.
- **Planner** is deterministic, side-effect-free, and non-optimizing. It constructs exactly these shapes:

~~~text
TableScanPlan

FilterPlan
  └── TableScanPlan

ProjectionPlan
  └── TableScanPlan

ProjectionPlan
  └── FilterPlan
        └── TableScanPlan
~~~

The public planning API is Plan, TableScanPlan, FilterPlan, ProjectionPlan, QueryRequest, Planner, and PlanningError.

## Phase 8: minimal SQL SELECT frontend

Phase 8 adds a narrow, dependency-downward frontend:

~~~text
SQL text
  ↓
Lexer → Parser → unresolved SQL AST → Binder
  ↓
QueryRequest → existing Planner → existing execution operators
~~~

The supported grammar is a single-table `SELECT` statement with either `*` or a comma-separated column list, an optional `WHERE` comparison against an integer, float, single-quoted string, or Boolean literal, and `IS NULL` / `IS NOT NULL`. Keywords and catalog/schema resolution are case-insensitive while identifier spelling is preserved. One optional trailing semicolon is allowed.

The frontend intentionally does not provide joins, aliases, qualified names, boolean combinations, expressions, aggregates, ordering, limits, mutations, SQL comments, multiple statements, or `StrataEngine.execute()` integration. Binding resolves only the table and translates SQL syntax to existing `QueryRequest` and predicate types; existing plans and predicates remain authoritative for column, duplicate-projection, and literal-type validation.

## Repository structure

~~~text
Strata/
├── src/
│   ├── strata_engine/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── storage/            # Pages, slotted pages, buffer pool, heap files
│   │   ├── schema/             # Types, columns, schemas, tuples, serialization
│   │   ├── catalog/            # Persistent catalog metadata and Table
│   │   ├── execution/
│   │   │   ├── operator.py
│   │   │   ├── table_scan.py
│   │   │   ├── filter.py
│   │   │   ├── projection.py
│   │   │   └── predicate.py
│   │   └── planning/
│   │       ├── plan.py
│   │       ├── table_scan_plan.py
│   │       ├── filter_plan.py
│   │       ├── projection_plan.py
│   │       ├── query_request.py
│   │       └── planner.py
│   └── strata_backend/
│       ├── main.py             # FastAPI entry point and GET /health
│       └── engine_adapter.py   # Backend-to-engine boundary
├── tests/                      # Storage through planning and integration tests
├── docs/                       # Architecture, development, and storage notes
├── data/                       # Reserved runtime data directory
└── pyproject.toml
~~~

## Quick start

Strata requires Python 3.10 or newer.

~~~bash
python --version
python -m venv .venv
~~~

Activate the virtual environment:

~~~powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
~~~

~~~bash
# Linux / macOS
source .venv/bin/activate
~~~

Install the package and development dependencies:

~~~bash
python -m pip install -e ".[dev]"
~~~

Run the automated suite:

~~~bash
python -m pytest
~~~

Start the development server:

~~~bash
python -m uvicorn strata_backend.main:app --reload --host 127.0.0.1 --port 8000
~~~

Verify the backend/engine boundary:

~~~bash
curl http://127.0.0.1:8000/health
~~~

~~~json
{
  "status": "ok",
  "service": "strata_backend",
  "engine": {
    "name": "StrataEngine",
    "status": "initialized",
    "initialized": true,
    "data_dir": null
  }
}
~~~

## Not yet implemented

The engine and application are intentionally incomplete. The following are not implemented:

- query optimizer, cost model, or statistics
- joins, aggregates, GROUP BY, ORDER BY, DISTINCT, LIMIT/OFFSET, or subqueries
- secondary indexes
- mutation planning or execution
- transactions, concurrency control, WAL, or recovery
- authentication or workspace/task domain backend features
- frontend client

## Future work

Future work is deliberately unnumbered until its sequencing is established. Likely areas include SQL parsing, richer execution (joins, aggregation, ordering, and limits), query optimization, indexes, mutation support, transactions and recovery, backend domain features, and a frontend client.
