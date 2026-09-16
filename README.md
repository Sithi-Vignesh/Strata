# Strata

> **Collaborative project and task-management application powered by a custom relational database engine written from scratch in Python.**

---

## 1. Academic Context

- **Course**: CSE302L — Database Systems
- **Lab**: BCSE302P — Database Systems Lab

The long-term objective of Strata is to demonstrate core database management system principles by engineering a relational database engine from scratch in Python, and powering a collaborative task-management application backend on top of it.

---

## 2. Project Status: Phase 5 — System Catalog, Schema, and Table Metadata

**Strata is currently in Phase 5.**

Phase 5 introduces relational typing, schema validation, binary record serialization, relational table abstractions, and a persistent system catalog.

### What is Implemented:
- **`strata_engine.schema`**:
  - `DataType`: Supported types (`INTEGER`, `BIGINT`, `FLOAT`, `BOOLEAN`, `VARCHAR`).
  - `Column`: Immutable column definition with identifier validation (`^[A-Za-z_][A-Za-z0-9_]{0,63}$`), strict nullability, and VARCHAR max length rules.
  - `Schema`: Immutable sequence of columns (1–256), case-preserving names, case-insensitive lookups, duplicate detection, and deterministic 32-bit CRC32 schema fingerprinting.
  - `Tuple`: Immutable relational row container supporting ordinal and case-insensitive named access, strict equality contract, and unhashable semantics.
  - `TupleSerializer`: Binary serializer with big-endian packing, null bitmap (LSB-first), UTF-8 text encoding, strict type checks, 4084-byte boundary enforcement, and corruption detection.
  - Schema Exceptions: `SchemaError`, `InvalidColumnError`, `DuplicateColumnError`, `InvalidSchemaError`, `ColumnNotFoundError`, `InvalidTypeError`, `SerializationError`, `TupleArityError`, `TupleSizeError`, `TypeMismatchError`, `ValueOutOfRangeError`, `NullConstraintError`, `CorruptRecordError`, `SchemaMismatchError`.
- **`strata_engine.catalog`**:
  - `Table`: Relational table abstraction wrapping a `HeapFile` and `Schema` with typed `insert()`, `get()`, `delete()`, `scan()`, `count()`, and lifecycle management.
  - `Catalog`: Persistent system catalog managing `<data_dir>/catalog/tables.db` and `<data_dir>/catalog/columns.db`, persistent monotonic High-Water Mark (HWM) table ID allocation without ID reuse, physical file-per-table mapping (`tables/table_{id}.db`), orphan file reconciliation, and DDL operations (`create_table`, `get_table`, `has_table`, `drop_table`, `list_tables`).
  - Catalog Exceptions: `CatalogError`, `CatalogCorruptionError`, `TableNotFoundError`, `TableAlreadyExistsError`, `ReservedNameError`.
- **`strata_engine`**:
  - `StrataEngine`: Full database lifecycle management (`open()`, `close()`, context manager), table management delegators, and status reporting.
- **`strata_engine.storage`**:
  - Unchanged Phase 1–4 storage primitives: `Page`, `PageId`, `PageFile`, `RecordId`, `SlottedPage`, `ClockReplacer`, `BufferPoolManager`, `HeapFile`.
- **`strata_backend`**: FastAPI application providing `GET /health` with `EngineAdapter`.
- **Automated Tests**: 236 unit and integration tests across storage, heap files, schemas, serialization, table operations, catalog persistence, and health endpoints.

### What is Intentionally NOT Implemented in Phase 5:
- No SQL lexer, parser, or AST generation (Planned: Phase 6)
- No query execution engine or Volcano iterators (Planned: Phase 7)
- No B+ tree secondary indexing (Planned: Phase 8)
- No transactions, WAL logging, or crash recovery (Planned: Phase 9)
- No query optimizer or EXPLAIN plans
- No overflow / chained large object pages (> 4084 bytes)
- No user authentication or workspace domain backend
- No frontend client

---

## 3. Technology Stack

- **Language**: Python (`>=3.10`, tested on Python 3.12)
- **API Framework**: FastAPI (`>=0.110.0`)
- **ASGI Web Server**: Uvicorn (`>=0.28.0`)
- **Testing**: pytest (`>=8.0.0`), HTTPX (`>=0.27.0` for in-process TestClient)
- **Build System**: setuptools (`pyproject.toml`)

*No external database engines (SQLite, PostgreSQL, MySQL, MongoDB, SQLAlchemy, Redis) or ORMs are used. All database engine components will be implemented from scratch.*

---

## 4. Repository Structure

```
Strata/
|
├── src/
│   ├── strata_engine/
│   │   ├── __init__.py         # Package root exporting StrataEngine
│   │   └── engine.py           # Core engine class and status interface
│   │
│   └── strata_backend/
│       ├── __init__.py         # Package root exporting EngineAdapter
│       ├── main.py             # FastAPI entrypoint and GET /health route
│       └── engine_adapter.py   # In-process adapter bridging backend and engine
│
├── tests/
│   ├── __init__.py             # Test package marker
│   ├── test_engine.py          # Unit tests for StrataEngine
│   └── test_health.py          # Integration tests for GET /health endpoint
│
├── docs/
│   ├── architecture.md         # Architecture boundaries & component roadmap
│   └── development.md          # Local developer setup & workflow guide
│
├── data/
│   └── .gitkeep                # Reserved directory for future runtime database files
│
├── pyproject.toml              # Project metadata, dependencies, and packaging
├── README.md                   # Project overview and setup instructions
├── .gitignore                  # Git ignore rules for Python, caches, and DB files
└── .env.example                # Safe template for environment configuration
```

---

## 5. Quick Start & Developer Guide

### 5.1 Check Python Version
Ensure Python 3.10+ is installed:
```bash
python --version
```

### 5.2 Create and Activate Virtual Environment
```powershell
# Create virtual environment
python -m venv .venv

# Activate on Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate on Linux / macOS
source .venv/bin/activate
```

### 5.3 Install Dependencies in Editable Mode
```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 5.4 Run Automated Tests
```bash
python -m pytest -v
```

### 5.5 Start the Development Server
```bash
python -m uvicorn strata_backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 5.6 Access the Health Endpoint
Verify backend-to-engine communication by sending a GET request to `/health`:
```bash
curl http://127.0.0.1:8000/health
```

**Response:**
```json
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
```

### What the Health Endpoint Proves:
1. The FastAPI web framework starts and processes HTTP requests correctly.
2. The `strata_backend` package successfully imports and instantiates the `EngineAdapter`.
3. The `EngineAdapter` communicates with `StrataEngine` in-process.
4. `StrataEngine` initializes and deterministically reports its status.
5. The full communication path `Client -> FastAPI -> Adapter -> Engine -> Response` is verified and functioning.

---

## 6. Next Planned Phase: Phase 5 — System Catalog & Schema Management

With Phase 4 verified, the planned next phase will focus on:
- System catalog tables for relational metadata storage (table schemas, column definitions, data types).
- Table schema definitions and data type system (INTEGER, VARCHAR, BOOLEAN).
- Tuple serialization and deserialization converting relational rows to/from opaque HeapFile records.
- Named table lookup and metadata persistence.


