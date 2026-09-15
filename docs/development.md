# Strata Development Guide — Phase 0

This document outlines the local development workflow, environment configuration, testing procedures, and engineering guidelines for **Strata**.

---

## 1. Prerequisites & Python Check

Strata requires **Python 3.10** or newer (developed and validated on Python 3.12).

Verify the installed Python version:

```bash
python --version
```

Ensure `pip` is available:

```bash
python -m pip --version
```

---

## 2. Virtual Environment Setup

Always isolate project dependencies within a local virtual environment named `.venv`.

### Step 2.1: Create the Virtual Environment

From the repository root (`Strata/`):

```bash
python -m venv .venv
```

### Step 2.2: Activate the Virtual Environment

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
.\.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

---

## 3. Installing Dependencies & Editable Installation

Upgrade `pip` and install the package along with development/testing dependencies in editable mode:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Editable mode (`-e`) links the `src/` directory directly into the virtual environment, allowing changes in `src/strata_engine` and `src/strata_backend` to be reflected immediately without manual reinstallations or `PYTHONPATH` manipulation.

---

## 4. Running the Test Suite

Run the automated test suite using `pytest`:

```bash
python -m pytest
```

For verbose output detailing each test case:

```bash
python -m pytest -v
```

All tests must pass cleanly before any code is committed.

---

## 5. Starting the FastAPI Development Server

To launch the FastAPI development server with auto-reload:

```bash
python -m uvicorn strata_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Once running, access the interactive OpenAPI documentation at:
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

---

## 6. Accessing the Health Endpoint

To verify backend-to-engine communication, query the `GET /health` endpoint:

**Using PowerShell:**
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health | ConvertTo-Json
```

**Using curl:**
```bash
curl -X GET http://127.0.0.1:8000/health
```

**Expected JSON Response:**
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

---

## 7. Phase 0 Validation Workflow

Before advancing to future phases, verify the following checklist:
1. `StrataEngine` imports directly from `strata_engine`.
2. `EngineAdapter` properly wraps engine calls without exposing private internals.
3. `fastapi.testclient.TestClient` successfully queries `/health` with HTTP 200.
4. No persistent database files or `.db` files exist in the repository root or in `data/`.
5. No third-party database engines (SQLite, PostgreSQL, SQLAlchemy) have been introduced.
6. All pytest tests in `tests/test_engine.py` and `tests/test_health.py` pass without warnings or errors.

---

## 8. Principles for Future Development

1. **Strict Phased Progression**: Each phase must be fully implemented, documented, and tested before subsequent phases begin.
2. **Zero Forbidden Database Dependencies**: Strata is built to demonstrate database engine concepts from scratch. External ORMs or database servers must never be substituted for our own engine.
3. **Decoupled Architecture**: Routes must only communicate through domain services and adapters, never manipulating physical database pages directly.
4. **Test-Driven Rigor**: All algorithms (slotted page packing, buffer eviction, B+ tree split/merge, lock tables) must have dedicated unit tests verifying edge cases.
