# Strata

> **Collaborative project and task-management application powered by a custom relational database engine written from scratch in Python.**

---

## 1. Academic Context

- **Course**: CSE302L — Database Systems
- **Lab**: BCSE302P — Database Systems Lab

The long-term objective of Strata is to demonstrate core database management system principles by engineering a relational database engine from scratch in Python, and powering a collaborative task-management application backend on top of it.

---

## 2. Project Status: Phase 0 — Repository Foundation

**Strata is currently in Phase 0.**

In Phase 0, the repository foundation, packaging, architecture boundaries, and health check communication flow are established and verified.

### What is Implemented in Phase 0:
- **`strata_engine`**: A minimal `StrataEngine` class with deterministic status reporting and explicit placeholder interface for SQL execution.
- **`strata_backend`**: A FastAPI application providing `GET /health`.
- **`EngineAdapter`**: An in-process boundary adapter allowing the FastAPI backend to query `StrataEngine` status without coupling to engine internals.
- **Automated Tests**: Comprehensive `pytest` test suite covering engine initialization, status determinism, placeholder behavior, and backend health endpoint responses.
- **Packaging**: Standard src-based layout with `pyproject.toml` supporting editable installation.
- **Documentation**: Architecture specifications and developer setup guides.

### What is Intentionally NOT Implemented in Phase 0:
Phase 0 does not implement any actual database engine internals or frontend applications:
- No page-oriented storage or slotted page records
- No disk database files or file manager
- No buffer pool manager or page eviction
- No system catalog or table schemas
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

## 6. Next Planned Phase: Phase 1 — Storage Engine Foundation

With Phase 0 verified, the planned next phase will focus on:
- Designing a page-based binary storage format (fixed-size pages, slotted page architecture).
- Implementing serialization and deserialization of records into binary page buffers.
- Building a disk File Manager to allocate, read, and write pages safely to persistent files in the `data/` directory.
