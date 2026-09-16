# Strata Storage Engine — Storage Foundation & Slotted-Page Layer

This document describes the design, architecture, binary layout, and usage of Strata's disk-backed storage engine (`strata_engine.storage`), covering Phase 1 (raw block I/O) and Phase 2 (slotted-page record storage).

---

## 1. Concepts and Fundamentals

### What is a Page?
A **Page** is the fundamental atomic unit of disk I/O in Strata. It is a fixed-size contiguous block of bytes (default 4096 bytes) in memory that maps directly to an identical block on disk.

### What is a Slotted Page?
While a raw `Page` is an unstructured sequence of bytes, a **SlottedPage** organizes that fixed-size page to support storing multiple **variable-length opaque byte records**.

In relational database systems, records vary in size and can be inserted or deleted dynamically. If records were stored contiguously without indirection:
1. Deleting a record in the middle would require shifting all subsequent records, or leaving unfillable holes.
2. External references to records (such as secondary indexes or foreign keys) would break every time neighboring records moved.

A slotted page solves this by introducing a **Slot Directory**:
- The slot directory grows **forward** from the front of the page.
- Record byte payloads grow **backward** from the end of the page.
- External references address a record by its `RecordId(page_id, slot_id)`. The slot directory acts as an indirection table: `slot_id` points to the physical offset where the record resides.
- Moving or compacting records updates only the slot directory offset; the `RecordId` remains stable.

### Authoritative Page Size
Strata standardizes on **4096 bytes** (4 KB):
```python
from strata_engine.storage import PAGE_SIZE

assert PAGE_SIZE == 4096
```

---

## 2. On-Disk Binary Layout of a Slotted Page

```
+-----------------------------------------------------------------------+
|  PAGE HEADER (8 bytes)                                                |
|  - magic (2B, uint16, 0x5350)                                         |
|  - flags (2B, uint16)                                                 |
|  - slot_count (2B, uint16)                                            |
|  - free_space_offset (2B, uint16)                                     |
+-----------------------------------------------------------------------+
|  SLOT DIRECTORY (grows forward: 4 bytes per slot)                     |
|  - Slot 0: [offset (2B), length (2B)]                                 |
|  - Slot 1: [offset (2B), length (2B)]                                 |
|  - ...                                                                |
|  - Slot N-1: [offset (2B), length (2B)]                               |
+-----------------------------------------------------------------------+
|  CONTIGUOUS FREE SPACE                                                |
|  (starts at: 8 + slot_count * 4; ends at: free_space_offset)          |
+-----------------------------------------------------------------------+
|  RECORD DATA (grows backward from offset 4096)                        |
|  - Record N-1                                                         |
|  - ...                                                                |
|  - Record 1                                                           |
|  - Record 0                                                           |
+-----------------------------------------------------------------------+
```

### 2.1 Header Fields (`PAGE_HEADER_FORMAT = ">HHHH"`, 8 bytes)
- **`magic` (uint16)**: Format marker `0x5350` (ASCII `"SP"`). Verifies valid page type and detects corruption.
- **`flags` (uint16)**: Reserved flags for future page attributes (e.g. overflow or directory pages).
- **`slot_count` (uint16)**: Total number of slots in the slot directory (both active and deleted).
- **`free_space_offset` (uint16)**: Byte offset marking the lower boundary of record storage. Initially 4096 (`PAGE_SIZE`), decreasing as records are appended.

### 2.2 Slot Directory Entry (`SLOT_ENTRY_FORMAT = ">HH"`, 4 bytes)
- **`offset` (uint16)**: Absolute byte offset where the record starts within the 4096-byte page.
- **`length` (uint16)**: Byte length of the record.
- **Deleted Slot Representation**: When a record is deleted, its slot entry is set to `offset = 0` and `length = 0`. Since offset 0 is inside the page header, `offset == 0` is an unambiguous marker for an unused/deleted slot.

### 2.3 Free Space Calculations
- **Slot Directory End**: $\text{offset} = 8 + (\text{slot\_count} \times 4)$
- **Contiguous Free Space**: $\text{free\_space\_offset} - \text{slot\_directory\_end}$
- **Total Free Space**: $\text{PAGE\_SIZE} - \text{slot\_directory\_end} - \sum \text{live\_record\_lengths}$
- **Fragmentation**: $\text{Total Free Space} - \text{Contiguous Free Space}$ (represents space trapped in deleted record holes).

---

## 3. Core Operations on Slotted Pages

### 3.1 Record Insertion (`insert_record`)
1. Accepts variable-length raw bytes (including empty `b""`).
2. Checks for a reusable deleted slot (`offset == 0`). If found, no new slot directory space is required; otherwise, 4 bytes are required for a new slot entry.
3. Space Check:
   - If `contiguous_free_space >= space_needed`: proceed directly.
   - If `contiguous_free_space < space_needed` but `total_free_space >= space_needed`: trigger automatic **compaction** to defragment holes, then proceed.
   - If `total_free_space < space_needed`: raise `InsufficientSpaceError`.
4. Decrements `free_space_offset` by record length and copies bytes into page buffer.
5. Updates the slot entry with `(new_offset, length)`.
6. Returns the `slot_id`.

### 3.2 Record Retrieval (`get_record`)
1. Validates `0 <= slot_id < slot_count`. (Raises `InvalidSlotIdError` otherwise).
2. Inspects slot entry. If `offset == 0`, raises `RecordNotFoundError`.
3. Validates record bounds ($\text{free\_space\_offset} \le \text{offset}$ and $\text{offset} + \text{length} \le 4096$).
4. Returns an immutable `bytes` copy of the record data.

### 3.3 Record Deletion (`delete_record`)
1. Validates slot ID.
2. If already deleted (`offset == 0`), raises `RecordNotFoundError`.
3. Sets slot entry to `(offset=0, length=0)`.
4. The space becomes a dead hole (fragmented) until compaction occurs.

### 3.4 Page Compaction (`compact`)
1. Reallocates all active, live records contiguously from byte 4096 downward.
2. Resets `free_space_offset` to point to the new top of record data.
3. Updates the `offset` in every live slot entry.
4. **Stable Slot IDs**: Slot indices do not change during compaction; deleted slots remain at their indices with `(offset=0, length=0)`. Existing `RecordId` references remain valid.

---

## 4. Record Identifiers (`RecordId`)

A `RecordId` uniquely addresses a record across the entire database:
```python
from strata_engine.storage import RecordId, PageId

rid = RecordId(page_id=0, slot_id=2)
assert rid.page_id == PageId(0)
assert rid.slot_id == 2
```
- Rejects negative numbers, booleans, floats, and strings.
- Implements `__eq__` and `__hash__` for use in sets, dictionaries, and future index structures.

---

## 5. Storage Exception Hierarchy

```
StorageError (Base)
├── PageSizeError               # Raw data length != PAGE_SIZE (4096)
├── InvalidPageIdError           # Page ID is negative, bool, or non-int
├── PageNotFoundError            # Page ID not yet allocated in storage file
├── StorageClosedError           # Operation attempted on closed PageFile
├── StorageCorruptionError       # File size or binary layout invariant violated
│   └── SlottedPageCorruptionError  # Malformed magic, bad slot offset, or overlapping records
├── RecordSizeError             # Record exceeds maximum page capacity (4084 bytes)
├── RecordNotFoundError          # Slot ID is deleted or unallocated
├── InsufficientSpaceError       # Page cannot fit record even after compaction
└── InvalidSlotIdError           # Slot ID is negative, bool, or out of range
```

---

## 6. End-to-End Persistence Example with `PageFile`

```python
from pathlib import Path
from strata_engine.storage import PageFile, SlottedPage, RecordId

db_path = Path("data/example.db")

# 1. Allocate a page and insert records
with PageFile(db_path) as pf:
    pid = pf.allocate_page()
    sp = SlottedPage(page_id=pid)

    s0 = sp.insert_record(b"Task: Implement B+ Tree")
    s1 = sp.insert_record(b"Task: Write SQL Parser")

    rid0 = RecordId(pid, s0)
    rid1 = RecordId(pid, s1)

    # Persist slotted page through PageFile
    pf.write_page(pid, sp.to_page())

# 2. Reopen file and recover records
with PageFile(db_path) as pf_reopened:
    page = pf_reopened.read_page(0)
    recovered_sp = SlottedPage.from_page(page, page_id=0)

    assert recovered_sp.get_record(rid0.slot_id) == b"Task: Implement B+ Tree"
    assert recovered_sp.get_record(rid1.slot_id) == b"Task: Write SQL Parser"
```

---

## 7. Corruption Detection Invariants

When parsing an existing page (`SlottedPage.from_page(page)`):
1. **Magic Verification**: Header must start with `0x5350`.
2. **Boundary Checks**: $\text{slot\_directory\_end} \le \text{free\_space\_offset} \le 4096$.
3. **Slot Offset Validity**: Every active slot must satisfy $\text{free\_space\_offset} \le \text{offset}$ and $\text{offset} + \text{length} \le 4096$.
4. **Deleted Slot Invariant**: Any slot with `offset == 0` must have `length == 0`.
5. **No Overlapping Records**: Live record intervals $[\text{offset}, \text{offset} + \text{length})$ must not overlap.

---

## 8. Running the Storage Test Suite

Run the full storage test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_storage.py tests/test_slotted_page.py -v
```

Run all tests in the repository:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
