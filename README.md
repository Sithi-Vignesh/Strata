# Strata

> **Collaborative project and task-management application powered by a custom relational database engine written from scratch in Python.**

---

## 1. Academic Context

- **Course**: CSE302L — Database Systems
- **Lab**: BCSE302P — Database Systems Lab

The long-term objective of Strata is to demonstrate core database management system principles by engineering a relational database engine from scratch in Python, and powering a collaborative task-management application backend on top of it.

---

## 2. Project Status: Phase 4 — Heap File Record Storage

**Strata is currently in Phase 4.**

Phase 4 introduces multi-page record management via `HeapFile`, coordinating slotted pages across disk through the buffer pool with deterministic first-fit allocation and stable `RecordId` routing.

### What is Implemented:
- **`strata_engine.storage`**:
  - `PAGE_SIZE`: Authoritative 4096-byte page size.
  - `Page`: Fixed-size 4096-byte binary page abstraction with strict size validation, immutability export, and encapsulated `write_bytes()` buffer synchronization.
  - `PageId`: Non-negative page identifier mapping directly to offset $\text{PageId} \times 4096$.
  - `PageFile`: Disk-backed page storage manager supporting deterministic zero-fill allocation, random access read/write, file reopening/recovery, and corruption detection.
  - `RecordId`: Identifies records via `(page_id, slot_id)` with validation and hashing.
  - `SlottedPage`: Big-Endian binary slotted-page format with 8-byte header, 4-byte slot directory entries growing forward, and record byte payloads growing backward. Supports variable-length record insertion, retrieval, deletion, and defragmentation compaction with stable slot IDs.
  - `ClockReplacer`: Deterministic CLOCK (Second-Chance) replacement policy tracking unpinned frames.
  - `Frame`: Buffer frame descriptor tracking resident page, pin count, dirty status, and lifecycle.
  - `BufferPoolManager`: Fixed-capacity buffer pool manager mediating page fetch, allocation, pin/unpin reference counting, dirty page tracking, automatic writeback on eviction, and safe flushing.
  - `HeapFile`: Multi-page record collection abstraction supporting variable-length record insertion, retrieval by `RecordId`, deletion with slot reuse, first-fit page selection, and leak-proof table scanning without holding pins across generator yields.
  - Storage Exceptions: `PageSizeError`, `InvalidPageIdError`, `PageNotFoundError`, `StorageClosedError`, `StorageCorruptionError`, `RecordSizeError`, `RecordNotFoundError`, `InsufficientSpaceError`, `InvalidSlotIdError`, `SlottedPageCorruptionError`, `BufferPoolFullError`, `PageNotCachedError`, `InvalidPinCountError`.
- **`strata_engine`**: Minimal `StrataEngine` class with status reporting and `execute()` interface placeholder.
- **`strata_backend`**: FastAPI application providing `GET /health`.
- **`EngineAdapter`**: In-process adapter bridging backend routes and the database engine.
- **Automated Tests**: 152 unit and integration tests across heap files, buffer pool management, clock replacement, slotted pages, storage operations, engine lifecycle, and health endpoints.
- **Packaging**: Standard src-based layout with `pyproject.toml` supporting editable installation.
- **Documentation**: Architecture specifications, developer setup guides, and detailed storage engine documentation (`docs/storage.md`).

### What is Intentionally NOT Implemented in Phase 4:
Phase 4 does not implement higher-level relational database engine components or frontend applications:
- No system catalog or table schemas (Planned: Phase 5)
- No SQL lexer, parser, or AST generation
- No query execution engine or relational algebra iterators
- No B+ tree indexing or index lookups
- No query planner, optimizer, or EXPLAIN plans
- No transactions, WAL, or recovery
- No locking, strict 2PL, or deadlock detection
- No user authentication, roles, or workspace logic
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


