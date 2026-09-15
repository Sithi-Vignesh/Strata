# Strata Storage Engine — Phase 1

This document describes the design, architecture, invariants, and usage of Strata's disk-backed storage layer (`strata_engine.storage`).

---

## 1. Concepts and Fundamentals

### What is a Page?
A **Page** is the fundamental atomic unit of I/O in the Strata database engine. It represents a fixed-size contiguous block of bytes in memory that maps directly to an identical fixed-size block on disk.

All database abstractions in subsequent phases—slotted record storage, system catalog tables, and B+ tree index nodes—will be structured on top of raw pages.

### Why Fixed-Size Pages?
1. **Predictable Hardware Alignment**: Modern operating systems and disk controllers transfer data in fixed-size blocks (typically 4 KB sectors or clusters). Aligning database pages with hardware blocks eliminates read-modify-write penalties.
2. **Deterministic Offset Computation**: With fixed-size pages, locating any page on disk requires zero searching:
   $$\text{Disk Offset} = \text{PageId} \times \text{PAGE\_SIZE}$$
3. **Buffer Pool Simplification**: In Phase 2, the buffer pool manager will allocate fixed-size frames in memory. Every frame can host exactly one page, preventing external memory fragmentation.
4. **Clean Disk Space Management**: Reclaiming or overwriting pages operates at uniform block granularities without requiring complex variable-size compaction at the file level.

### Authoritative Page Size
Strata standardizes on **4096 bytes** (4 KB):
```python
from strata_engine.storage import PAGE_SIZE

assert PAGE_SIZE == 4096
```

---

## 2. Core Storage Abstractions

### 2.1 Fixed-Size Page (`Page`)
The `Page` class ([src/strata_engine/storage/page.py](file:///c:/Users/sithi/Coding/Strata/src/strata_engine/storage/page.py)) provides a byte-level container holding exactly 4096 bytes:
- **Blank Initialization**: `Page.blank()` generates a page initialized to 4096 null bytes (`0x00`).
- **Binary Ingest**: `Page.from_bytes(data)` accepts exact 4096-byte sequences.
- **Strict Validation**: Rejects undersized or oversized data immediately by raising `PageSizeError`.
- **Immutability & Safety**: `page.to_bytes()` returns an immutable `bytes` copy, preventing accidental alteration or resizing of internal buffers.

### 2.2 Page Identifier (`PageId`)
The `PageId` class ([src/strata_engine/storage/page_id.py](file:///c:/Users/sithi/Coding/Strata/src/strata_engine/storage/page_id.py)) encapsulates non-negative page numbers:
- Enforces $N \ge 0$.
- Rejects non-integers, floats, strings, and booleans (`InvalidPageIdError`).
- Directly corresponds to the sequential offset: $\text{Offset} = \text{PageId} \times 4096$.

### 2.3 Disk-Backed Page File (`PageFile`)
The `PageFile` class ([src/strata_engine/storage/page_file.py](file:///c:/Users/sithi/Coding/Strata/src/strata_engine/storage/page_file.py)) manages persistent file I/O:
- **Safe Creation/Open**: Opens existing files without truncating or creates new files if nonexistent (`r+b` mode).
- **Sequential Page Allocation**: `allocate_page()` appends a 4096-byte zero-filled block at the end of the file, flushes to disk, and returns the assigned `PageId`.
- **Direct Offset Reads**: `read_page(page_id)` reads 4096 bytes at offset $\text{page\_id} \times 4096$.
- **Direct Offset Writes**: `write_page(page_id, page)` overwrites the 4096 bytes at offset $\text{page\_id} \times 4096$. Requires the page to have been previously allocated (unallocated writes raise `PageNotFoundError`).
- **Corruption Detection**: Files whose sizes on disk are not exact multiples of 4096 bytes are flagged with `StorageCorruptionError` upon opening.
- **Safe Closure & Lifecycle**: Supports explicit `.close()` and context manager syntax (`with PageFile(...) as pf:`). Post-closure operations raise `StorageClosedError`.

---

## 3. Storage Exception Hierarchy

```
StorageError (Base)
├── PageSizeError             # Raw data length != PAGE_SIZE (4096)
├── InvalidPageIdError         # Page ID is negative, bool, or non-int
├── PageNotFoundError          # Page ID not yet allocated in storage file
├── StorageClosedError         # Operation attempted on closed PageFile
└── StorageCorruptionError     # File size not a multiple of PAGE_SIZE or truncated read
```

---

## 4. Usage Example

```python
from pathlib import Path
from strata_engine.storage import Page, PageFile, PAGE_SIZE

# 1. Open or create a storage file
with PageFile(Path("data/my_table.db")) as pf:
    # 2. Allocate a new page (returns PageId(0))
    pid = pf.allocate_page()
    assert int(pid) == 0

    # 3. Prepare 4096 bytes of page data
    content = b"HEADER_DATA" + (b"\x00" * (PAGE_SIZE - 11))
    page = Page(content)

    # 4. Write page to disk
    pf.write_page(pid, page)

    # 5. Read back page
    read_page = pf.read_page(pid)
    assert read_page.to_bytes() == content
```

---

## 5. What is Intentionally Deferred (Phase 1 Scope Limits)

The following components are **NOT** part of Phase 1 and will be introduced in subsequent phases:
- **Slotted Pages**: Slot directories, record pointers, variable-length record packing, and fragmentation management.
- **Buffer Pool Manager**: In-memory frame caching, pin/unpin counts, and eviction algorithms (LRU / Clock).
- **System Catalog**: Storing table schemas, column data types, or physical page mappings.
- **Write-Ahead Logging (WAL)**: Redo/undo log records, LSN tracking, and crash recovery protocols.
- **Transactions & Concurrency**: Locks, latches, or ACID isolation.

---

## 6. Running Storage Tests

Run the storage engine test suite using pytest:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_storage.py -v
```

Run all tests across the repository:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
