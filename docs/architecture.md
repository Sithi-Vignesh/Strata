# Strata Architecture — Phase 0

## 1. System Overview

**Strata** is an educational relational database management system and collaborative task-management application developed for **CSE302L / BCSE302P (Database Systems & Database Systems Lab)**.

The long-term objective of Strata is to demonstrate fundamental database engine concepts by building a relational database engine from scratch in Python, while driving realistic workloads through a task-management backend.

In **Phase 0 (Repository Foundation)**, no database engine internals (storage files, buffer manager, catalog, SQL execution, B+ trees, transactions) are implemented. Instead, Phase 0 establishes the software boundaries, package layouts, and an in-process adapter demonstrating verifiable backend-to-engine connectivity.

---

## 2. Architectural Boundaries: Backend vs. Engine

Strata strictly isolates application logic from database engine internals across two distinct packages:

```
+-------------------------------------------------------------+
|                      strata_backend                         |
|                                                             |
|   FastAPI App (Endpoints) ---> EngineAdapter                |
+--------------------------------------|----------------------+
                                       | In-process Python API
                                       v
+-------------------------------------------------------------+
|                      strata_engine                          |
|                                                             |
|   StrataEngine                                              |
|     |-- (Phase 0: Lifecycle initialization & status)        |
|     +-- (Future: Storage, Catalog, Planner, Execution)      |
+-------------------------------------------------------------+
```

### strata_backend
The backend package (`src/strata_backend`) is responsible for serving REST endpoints, managing HTTP requests/responses, serializing data, and in future phases, handling domain logic such as projects, tasks, user authentication, and workspace isolation. The backend never manipulates physical database files directly and never embeds raw storage algorithms.

### strata_engine
The engine package (`src/strata_engine`) houses the relational database engine. Its responsibility is pure database management: disk page layout, buffer pooling, catalog management, SQL parsing, query optimization, indexing, and transactional ACID guarantees.

### The Role of the Engine Adapter
The `EngineAdapter` (`strata_backend/engine_adapter.py`) acts as the mediator between the FastAPI HTTP routes and the `StrataEngine` instance:
- It shields backend route handlers from internal changes in the engine's public API.
- It translates backend intent into engine calls.
- In Phase 0, it calls `StrataEngine.status()` and passes formatted status information to the `GET /health` endpoint.
- In future phases, it will manage connection contexts, query dispatch, and result mapping.

---

## 3. Communication Flow & In-Process Invocation

### Phase 0 Health Check Flow

```
[ HTTP Client ]
      |
      |  GET /health
      v
[ FastAPI Route Handler (main.py) ]
      |
      |  get_status()
      v
[ EngineAdapter (engine_adapter.py) ]
      |
      |  status()
      v
[ StrataEngine (engine.py) ]
      |
      |  Returns deterministic status dict
      v
[ FastAPI Response: HTTP 200 JSON ]
```

### Why In-Process?
The backend initially invokes the database engine **in-process** via standard Python method calls:
- Eliminates unnecessary network protocol and IPC overhead during development.
- Keeps testing deterministic and self-contained without requiring external database servers (PostgreSQL, MySQL) or external daemon processes.
- Allows fine-grained inspection and unit testing of database algorithms (page management, locking, buffer replacement) directly within Python.

### Client / Frontend Isolation
When the frontend is created in later phases, it will **never** access database files or invoke engine methods directly. All client access is strictly routed through the FastAPI backend over REST/HTTP. This preserves security, centralized schema validation, authentication, and isolation guarantees.

---

## 4. Centralized Relational Design vs. Distributed Systems

- **Centralized Single-Node Architecture**: Strata is explicitly designed as a centralized relational database engine. All storage, memory management, indexing, and query processing occur on a single host.
- **Out of Scope**: Distributed database concepts—such as distributed consensus (Raft/Paxos), partition management, two-phase commit (2PC) over network nodes, distributed transactions, and data sharding—are strictly out of scope for Strata.

---

## 5. Application Data vs. Engine-Internal State

A clean conceptual separation is maintained between:
1. **Engine-Internal State**:
   - Page headers, slotted page records, page directories.
   - Buffer pool frame tables and replacement policies (LRU/Clock).
   - System catalog tables storing table schemas, column types, and indexes.
   - Lock tables, wait-for graphs for deadlock detection, transaction undo/redo logs.
2. **Application Data**:
   - User credentials, workspaces, roles, projects, tasks, notes, and activity history.
   - Application data resides purely within tables managed by the engine, queried via SQL commands issued by the backend adapter.

---

## 6. Implementation Status and Component Roadmap

| Component | Status | Description |
|---|---|---|
| Repository Layout & Packaging | **Implemented (Phase 0)** | Standard src-based layout, pyproject.toml, pytest suite |
| `StrataEngine` Core Class | **Implemented (Phase 0)** | Lifecycle initialization, status reporting, execute() placeholder |
| `EngineAdapter` | **Implemented (Phase 0)** | In-process boundary between backend and engine |
| `GET /health` Endpoint | **Implemented (Phase 0)** | Validated HTTP 200 endpoint returning engine status JSON |
| Fixed-Size Pages & Page File Storage | **Implemented (Phase 1)** | Fixed-size 4096-byte pages, PageId, PageFile manager |
| Slotted Page Record Storage | *Planned (Phase 2)* | Slotted page headers, record pointers, tuple serialization |
| Buffer Pool Manager | *Planned* | In-memory frame management and page replacement |
| System Catalog | *Planned* | Metadata storage for schemas and table definitions |
| SQL Lexer & Parser | *Planned* | Tokenization and AST generation for subset of SQL |
| Query Execution Engine | *Planned* | Volcano-style iterator model (Scan, Filter, Project, Join) |
| B+ Tree Indexing | *Planned* | Page-backed tree indexing for efficient point & range lookups |
| Query Optimizer & EXPLAIN | *Planned* | Cost-based / heuristic query planning and plan visualization |
| Transactions & Concurrency | *Planned* | Strict 2PL, shared/exclusive locks, deadlock detection |
| Workspace & Task Backend | *Planned* | Domain entities, auth, task management logic |
| Web Frontend | *Planned* | User interface for projects and tasks |
