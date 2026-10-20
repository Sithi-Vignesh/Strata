# Strata architecture

## Product scope boundaries

Authenticated product reads are split into account-wide and selected-workspace scopes. `GET /api/dashboard`, `GET /api/tasks`, and Inbox are global but membership-filtered on every request. `GET /api/workspaces/{id}/dashboard`, `GET /api/my/tasks?workspace_id=...`, Projects, Tasks, Board, and Members require current membership in the selected workspace. Frontend workspace state is a navigation preference, never an authorization boundary.

Task audit history is append-only. Logical task IDs are allocated above both live tasks and retained audit identities so deletion cannot cause cross-generation identity reuse. See [manual-review-fixes.md](manual-review-fixes.md) for the legacy compatibility rule.

## Runtime boundaries

The browser talks only to FastAPI. The backend owns two independent StrataEngine lifecycles: the product database and the SQL demonstration database. They must use different directories. Product routes call ProductService and the typed Table API; SQL routes call EngineAdapter and the parser/binder/planner/executor path. Neither path uses an external DBMS.

FastAPI synchronous request handlers run on worker threads. A lifespan creates each engine, bootstraps its schema and persistent indexes, and installs the product service. Shutdown closes engines after request handling stops. The supported deployment is one backend process/worker, multiple concurrent requests, and local disk.

## Product data model

| Table | Purpose and relationships |
| --- | --- |
| users | Logical ID, display name, canonical email, nullable Argon2id hash, account state, timestamps |
| workspaces | ID, name, PERSONAL/COLLABORATIVE kind, timestamps |
| workspace_members | Workspace ID, user ID, OWNER/MEMBER role; exactly one owner per workspace |
| projects | Workspace ID, name, description, immutable creator attribution, timestamps |
| tasks | Project ID, title/description, status/priority, nullable assignee, creator, timestamps |
| notes | Task ID, author ID, content, timestamps |
| sessions | User ID, SHA-256 digest of opaque token, creation and expiry timestamps |
| task_due_dates | Additive optional ISO calendar date keyed by task ID |
| task_activity | Append-only logical task events with retained project/workspace/actor identity |
| notifications | Persistent recipient-owned collaboration inbox and read/dismissal state |

Logical IDs are allocated under the shared database lock. They use the existing MAX + 1 strategy; deletion of the highest ID can permit reuse, so IDs are not globally monotonic. References and application uniqueness are service invariants, not native SQL constraints. Indexed lookup covers email, memberships by user/workspace, projects by workspace, tasks by project/assignee, notes by task, and sessions by token digest/user.

Due dates, activity history, cross-workspace assigned-task queries, handoff notes, and notifications are documented in [scope-c-backend.md](scope-c-backend.md). The sidecar design preserves legacy task tuple fingerprints and extends existing databases repeatably without rewriting user rows.

Registration provisions a personal workspace and initial project. A registered user can create a collaborative workspace and add another active registered user by normalized email. Membership is immediate. Only an owner can add/remove members, transfer ownership, or edit/delete a collaborative workspace. Personal workspaces cannot be renamed/deleted through the authenticated API and cannot gain members.

Members can create/edit projects and tasks and assign workspace members. Project/task deletion belongs to their creator; an owner can delete when that creator no longer has active membership. Note changes belong to the author, who must still have access. Removing a member clears assignments but preserves creator/note author IDs. Ownership transfer demotes/promotes the two membership rows while holding the database lock.

## Authentication and authorization

Passwords use Argon2id. Expensive hashing/verification happens outside the database critical section. Login rechecks the user is active before creating a session. The raw random token goes into an HttpOnly, SameSite=Lax cookie; only its digest is stored. Sessions last 30 days and are checked against server time. Logout resolves and revokes the presented token under one database lock, so a concurrent login cannot have a reused numeric session ID revoked by an older logout. STRATA_SESSION_COOKIE_SECURE=true is available for HTTPS deployments; local HTTP uses false.

Every product resource route derives its actor from the session dependency. Unauthorized resource reads use 404; visible resources with forbidden operations use 403. Membership-by-email checks workspace authorization before looking up the email. Request models reject unexpected fields, preventing client-supplied owner/author identities. The browser uses the Vite same-origin API proxy. CORS is not configured for credentialed requests from arbitrary other origins. Unsafe /api requests also check Origin against the incoming same-origin host or the configured frontend origin; Referer and Fetch Metadata provide fallback checks. This blocks same-site alternate-port logout CSRF. Headerless non-browser clients remain supported. Request validation rejects malformed Unicode and coerced body IDs; validation responses omit submitted values.

ProductService's actor_user_id=None mode is retained for trusted internal/bootstrap use. It is not an HTTP permission bypass: resource routes always supply the authenticated actor. Raw engine access likewise has no product authorization layer.

## Database concurrency and deadlock prevention

The implementation is in src/strata_engine/concurrency.py.

1. StrataEngine constructs one DatabaseLock (an RLock with a 30-second acquisition deadline).
2. Catalog, Table and catalog-owned BPlusTree instances receive that same object. ProductService instances and EngineAdapter reuse it rather than creating independent locks.
3. A service operation holds it across reads, permission checks, MAX + 1 allocation, heap writes and index maintenance. Password hashing is outside this section.
4. Engine SQL operations hold it through parse/bind/plan/execute and row materialization. Catalog DDL, Table insert/get/update/delete/count/scan/close and B+ tree operations also acquire it directly.
5. Nested calls reenter the same lock. There are no independently acquired table, page, heap or buffer locks on these paths. Thus workers cannot form an A-table/B-table acquisition cycle.
6. Context managers release the lock on success or exception. A timeout raises DatabaseBusyError; product and SQL HTTP routes return 503. It is not a detected deadlock or a rollback operation.

This is **deadlock prevention by coarse serialization**. It trades parallel reads/writes for a small, auditable correctness boundary. It is not serializable transactions, 2PL, MVCC, deadlock detection or automatic compensation of arbitrary statements.

Table.scan materializes records under the lock before returning an iterator. Holding or abandoning that iterator cannot retain the database lock or pin a page. TableScan still reports a closed-table error if its table is closed mid-lifecycle. Snapshots cost memory proportional to the table. Direct scans are snapshots; the complete SQL operator lifecycle is protected by the outer engine lock.

HeapFile, BufferPoolManager, CLOCK, PageFile, Page and SlottedPage remain low-level primitives without independent synchronization. Their buffer maps, frame pin counts/dirty flags, file offsets, page allocation and byte mutations are protected when reached through the coordinated Table/SQL/service paths. For manual compound access or custom execution operators, use:

~~~python
with engine.operation():
    table = engine.get_table("tasks")
    # Perform the complete compound operation here.
~~~

Never mutate raw pages or attach independently locked trees to a shared database outside this context. Standalone raw-storage primitives support single-threaded use. Do not acquire a second database lock, await, join a database worker, or run a callback that does so while holding the first. These external lock/wait patterns are outside the supported model; application paths do not use them.

### Directory ownership

Catalog opens a permanent .strata.lock file and obtains a nonblocking OS advisory lock (msvcrt byte lock on Windows; flock on POSIX). A second catalog or engine on the same resolved directory fails with DatabaseInUseError before opening storage. The handle is retained until normal close and released on initialization failure. The OS releases it if the process exits; never delete the lock file to force access.

This prevents accidental multi-worker deployment and duplicate caches. It does not enable multi-process reads/writes, protect against programs that ignore the guard, or recover partially written data. Network/shared filesystem locking is not supported. The cross-process rejection test was executed on Windows; the POSIX branch is provided but was not exercised in this sprint.

### Evidence

Tests in tests/test_concurrency.py use events, barriers, bounded joins and exception propagation. They hold the shared lock and observe competing acquisition attempts through services (including a second instance), SQL, profiled SQL, adapter, catalog, table scan/read, indexes and close. An opposite-table-order experiment makes a second worker contend while the first owns the lock; both finish, indexed rows match and survive reopen. Additional cases cover concurrent patches/ID allocation, duplicate additions, ownership transfer, removal-versus-assignment, exception release, abandoned scans, timeout behavior and directory ownership.

## Persistence and failures

Dirty heap buffers flush on eviction/normal close; indexes persist nodes and header metadata. Catalog metadata and indexes reopen from their own files. Updates preserve the RID where possible and relocate otherwise. Table updates maintain index entries and attempt row-local compensation on failure. Registration/workspace creation compensate inserted rows; membership transfer/removal attempt to restore roles/assignments. Ownership rollback retains the actual RID returned by a potentially relocating demotion. Failed task/workspace deletion restores completed child deletes, and reports an explicit service error if restoration fails. B+ tree mutations retain touched-node before-images and structural counters to recover from transient split/node-write failures.

These compensations are not transactions. SQL multi-row mutations may leave earlier writes applied after an I/O failure. Persistent I/O faults or a failed inverse can also leave partial changes despite the focused compensations. There is no WAL, fsync-based durability contract, arbitrary-crash recovery or automatic repair. Normal close/reopen, API restart and indexed mutation persistence are verified; sudden process termination is not a recovery guarantee.

## SQL and storage foundations

4096-byte pages contain slotted records. Typed tuples and schema fingerprints sit above HeapFile; persistent catalog metadata maps logical names to table/index files. B+ trees handle supported typed keys and RIDs. The SQL frontend uses a lexer, recursive-descent parser and binder. The deterministic planner selects table/index scans, unary filters/projections/sorts/limits, aggregates and a constrained nested-loop join. Volcano operators execute through open/next/close. Profiles count logical traversal work.

These are established database concepts implemented for this project. Their value is demonstrated by persisted multi-user workflows and inspectable storage/query behavior. No novelty, full SQL compatibility or ACID claims are made.
