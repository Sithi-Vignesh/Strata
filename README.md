# Strata

> A CSE302L / BCSE302P Database Systems project: a custom relational database engine written from scratch in Python, with a future application backend and frontend.

Strata is built bottom-up—storage first, then relational data, query execution and planning, SQL, and finally application features. It uses no external database engine or ORM.

## Status

**Phase 18 — Minimal SQL DROP TABLE is implemented.** `StrataEngine.execute()` supports the existing SELECT pipeline, constrained `INSERT INTO table VALUES (...)` commands, and minimal `CREATE TABLE` and `DROP TABLE` commands.

Phase 13’s authoritative baseline was **472 passed**, **2 known third-party deprecation warnings**, and **0 failures**. Run the repository test suite to verify the current Phase 14 working tree.

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
| 7 — Query Planning | Immutable reusable plan trees that construct fresh operator trees. |
| 8 — Minimal SQL SELECT Frontend + Binding | A read-only SQL frontend that binds syntax to existing query intent. |
| 9 — Compound Predicate Expressions | Boolean WHERE composition with AND, OR, NOT, parentheses, and conventional precedence. |
| 10 — ORDER BY + LIMIT/OFFSET | Stable in-memory ordering and streaming pagination. |
| 11 — Global Aggregation | Blocking `COUNT(*)`, `COUNT(column)`, `SUM`, `AVG`, `MIN`, and `MAX`. |
| 12 — Two-table INNER JOIN | One equality INNER JOIN with qualified references, joined WHERE/ORDER BY, and pagination. |
| 13 — GROUP BY / Grouped Aggregation | Single-table grouping with one or more columns, existing aggregates, mixed/interleaved output, post-aggregate ORDER BY, and LIMIT/OFFSET. |
| 14 — Two-table INNER JOIN + Aggregation | Global and grouped aggregation over one equality INNER JOIN, including qualified/unique unqualified references and post-aggregate ordering. |
| 15 — Engine SQL Integration | Public `StrataEngine.execute()` facade that materializes existing SELECT results as `QueryResult`. |
| 16 — Minimal SQL INSERT | One ordered literal VALUES row inserted through the existing typed table path. |
| 17 — Minimal SQL CREATE TABLE | Persistent table creation through the existing schema and catalog path. |
| 18 — Minimal SQL DROP TABLE | Persistent table deletion through the existing catalog path. |

## Current architecture

The engine layers remain deliberately one-directional:

```text
SQL
 ↓
Planning
 ↓
Execution
 ↓
Schema / Catalog / Table
 ↓
Heap / Buffer Management
 ↓
Pages / Records
 ↓
Disk
```

SQL AST nodes are immutable, syntax-only, and unresolved. The Binder translates syntax into resolved query intent; the Planner turns that intent into physical plan trees. Execution does not depend on Planning or SQL, and Planning does not depend on SQL. The backend uses the public engine API through `EngineAdapter` and does not manipulate storage internals.

## Historical phase notes

Phase 5 introduced typed relational data: `DataType`, immutable `Column` and `Schema`, schema-bound `Tuple`, binary serialization, persistent `Catalog`, and `Table` insert/get/delete/scan/count operations.

At the completion of Phase 6, query execution introduced the Volcano-style `TableScan`, `Filter`, and `Projection` operators with explicit `open()` / `next()` / `close()` lifecycle rules. At that historical point, joins, aggregates, sorting, SQL parsing, and pagination had not yet been implemented; later phases added them.

Phase 7 introduced immutable reusable plans. Each `create_operator()` call creates a fresh unopened tree. Current plans include scan, filter, projection, sort, limit, aggregate, join, and join-projection planning.

## Current SQL capability

The SQL frontend supports a deliberately narrow SELECT subset:

- single-table SELECT with `*` or explicit projection;
- `WHERE`, including `AND`, `OR`, `NOT`, parentheses, comparisons, `IS NULL`, and `IS NOT NULL`;
- source-column `ORDER BY` with ASC/DESC and multiple items;
- `LIMIT` and `LIMIT ... OFFSET ...`;
- global aggregation with `COUNT(*)`, `COUNT(column)`, `SUM`, `AVG`, `MIN`, and `MAX`;
- single-table `GROUP BY` with one or more source columns, mixed/interleaved grouping and aggregate SELECT items, and post-aggregate ordering by exposed output names;
- exactly one two-table equality `JOIN` / `INNER JOIN`, explicit projections, joined WHERE, joined ORDER BY, and joined LIMIT/OFFSET.
- global and grouped aggregation over that two-table JOIN, with qualified or uniquely resolvable unqualified aggregate/grouping references; joined WHERE runs before aggregation, while grouped ORDER BY and LIMIT/OFFSET run afterward.

For grouped queries, WHERE runs before aggregation, ORDER BY runs after aggregation, and LIMIT/OFFSET runs last. Every ordinary selected column must appear in `GROUP BY`; GROUP BY without aggregates is unsupported. Generated aggregate output names such as `count_star` may be used as grouped ordering names.

For example:

```sql
SELECT department, COUNT(*), AVG(salary)
FROM employees
WHERE active = TRUE
GROUP BY department
ORDER BY department
LIMIT 10;
```

The SQL subset intentionally does not support HAVING, aliases, DISTINCT or DISTINCT aggregates, aggregate-call ordering such as `ORDER BY COUNT(*)`, global aggregate ORDER BY, multiple/chained joins, outer joins, non-equality JOIN conditions, or general scalar expressions.

Execute the supported SELECT subset through the engine facade. `QueryResult` retains the output schema even when no rows match, and its rows are existing schema-bound `Tuple` values:

```python
from strata_engine import Column, DataType, Schema, StrataEngine

with StrataEngine("database") as engine:
    users = engine.create_table("users", Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR, max_length=32),
    ]))
    users.insert([1, "Ada"])

    result = engine.execute("SELECT name FROM users")
    print(result.schema.column_names)
    for row in result.rows:
        print(row.values)
```

`execute()` supports the existing SELECT subset, constrained INSERT, and the minimal CREATE TABLE and DROP TABLE forms below.

The first supported SQL mutation is a deliberately constrained INSERT:

```python
inserted = engine.execute("INSERT INTO users VALUES (2, 'Bea')")
assert inserted.affected_rows == 1
```

INSERT accepts exactly one literal row, requires all table columns in schema order, and returns `CommandResult(affected_rows=1)`. Column lists, multi-row VALUES, `INSERT ... SELECT`, and `RETURNING` are not supported.

Minimal SQL CREATE TABLE accepts one or more ordered columns using `INTEGER`, `BIGINT`, `FLOAT`, `BOOLEAN`, or required-length `VARCHAR(n)`:

```python
created = engine.execute("CREATE TABLE users (id INTEGER, name VARCHAR(100))")
assert created.affected_rows == 0
```

All SQL-created columns are currently non-nullable. Minimal `DROP TABLE table_name` is supported and returns `CommandResult(affected_rows=0)`. `NULL`/`NOT NULL`, `PRIMARY KEY`, `UNIQUE`, `DEFAULT`, `CHECK`, `FOREIGN KEY`, `IF EXISTS`, `CREATE TABLE AS SELECT`, `ALTER`, `CASCADE`, `RESTRICT`, and DDL transactions/recovery are unsupported. CREATE, INSERT, DROP, and SELECT can form a basic SQL-only workflow.

## Repository structure

```text
Strata/
├── src/
│   ├── strata_engine/
│   │   ├── storage/       # pages, records, slotted pages, heap files, buffer pool
│   │   ├── schema/        # types, columns, schemas, tuples, serialization
│   │   ├── catalog/       # persistent catalog metadata and tables
│   │   ├── execution/     # scans, predicates, filter, projection, sort, limit,
│   │   │                  # aggregate, nested-loop join, join projection
│   │   ├── planning/      # immutable plans, query intent, sorting, limits,
│   │   │                  # aggregation, joins, and projection planning
│   │   ├── sql/           # tokens, lexer, AST, parser, binder, SQL errors
│   │   └── engine.py      # public engine facade
│   └── strata_backend/    # FastAPI entry point and EngineAdapter
├── tests/                 # storage through SQL and integration coverage
├── docs/                  # architecture, development, and storage notes
├── data/                  # reserved runtime data directory
└── pyproject.toml
```

## Quick start

Strata requires Python 3.10 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start the backend development server with:

```bash
python -m uvicorn strata_backend.main:app --reload --host 127.0.0.1 --port 8000
```

## Not yet implemented

- query optimizer, cost model, or statistics;
- HAVING;
- aliases, DISTINCT, DISTINCT aggregates, subqueries, and broader expression support;
- multiple/chained joins, outer joins, and non-equality join conditions;
- secondary indexes;
- SQL mutation planning and execution;
- transactions, concurrency control, write-ahead logging, or recovery;
- application-domain backend features and a frontend client.

## Future work

Future work remains deliberately unnumbered until sequencing is selected. Likely directions include optimization and statistics, indexes, mutation operators, transactions and recovery, richer SQL composition such as HAVING and subqueries, broader join support, and the application backend and frontend.
