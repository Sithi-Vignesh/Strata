# Database benchmarking and integrity verification

## Architecture and safety

`benchmarks/run.py` exercises the public `StrataEngine` SQL interface and the real product service. Every invocation creates a uniquely named `strata-benchmark-*` directory directly beneath the operating-system temporary directory. The harness verifies that location before creating data and again before recursively removing it. It never accepts a database path and cannot fall back to developer or product storage.

The harness writes only reports to `--output-dir`; database files remain disposable. The default output is `.verification/benchmarks/latest`, which is ignored by Git.

The future P4 runner can invoke the bounded smoke profile and consume `results.json`. Exit code zero means all measured workloads and correctness experiments completed; nonzero means setup or verification failed. Absolute timing thresholds are intentionally absent.

## Profiles and commands

From the repository root in Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe benchmarks\run.py --profile smoke --output-dir .verification\benchmarks\smoke
.\.venv\Scripts\python.exe benchmarks\run.py --profile full --output-dir .verification\benchmarks\full
```

Smoke uses 100 and 1,000 rows, three measured iterations, one warm-up, and 12 mixed concurrent operations. Full uses 100, 1,000, and 5,000 rows, seven measured iterations, two warm-ups, and 30 mixed operations. Overrides are explicit:

```powershell
.\.venv\Scripts\python.exe benchmarks\run.py --profile smoke --sizes 50,500 --iterations 5 --warmups 2 --concurrency-operations 16 --output-dir .verification\benchmarks\custom
```

Each output directory contains:

- `results.json`: versioned machine-readable configuration, environment, measurements, profiles, correctness results, and limitations;
- `report.md`: a compact human-readable table and interpretation notes.

## Supported workloads

The measured SQL workloads are full-table scan, equality and range filtering, indexed point and range lookup, `ORDER BY`, `LIMIT`, `COUNT`/`SUM`/`AVG`/`MIN`/`MAX`, `GROUP BY`, and nested-loop `INNER JOIN`. Setup and index-build time are reported separately.

The scan and indexed tables contain the same deterministic seeded rows. Before a speedup ratio is emitted, the harness verifies result equivalence and confirms actual `TableScan` and `IndexScan` profiles. Each query is warmed independently; recorded results are warm-cache observations because the buffer pool has no public deterministic cache-reset operation.

For an `AND` predicate, the current non-optimizing planner selects the first eligible indexed comparison. A two-sided range such as `id >= lower AND id <= upper` therefore scans the B+ tree suffix from `lower`, fetches those rows, and evaluates the upper bound as a residual filter. The range experiment records this behavior and may honestly show a slowdown even though an index path was used.

Join execution is measured, but no access-path profile is claimed because the engine deliberately exposes a profile only for a singular single-table scan.

## Integrity methodology

The suite maintains a deterministic in-memory expected model while inserting, relocating/updating, and deleting rows. It then checks:

- exact row contents and unique logical IDs;
- every B+ tree entry against heap records;
- B+ tree structural validation and entry counts;
- absence of pinned buffer frames;
- record counts and index consistency after engine restart.
- cross-workspace invisibility and post-revocation task unassignment;
- task deletion cleanup for notes and due-date sidecars, while recognizing task activity as intentionally retained audit history.

The compensation experiment injects one recoverable B+ tree maintenance failure and verifies the heap/index snapshot before and after restart. A product task-update failure is injected at activity creation; the task must be restored and no false activity or notification row may remain.

These checks demonstrate supported in-process compensation. They do not establish transaction atomicity under process termination, power loss, or arbitrary I/O failure.

## Concurrency methodology

Four `ProductService` instances share one engine and one process-local database lock. Bounded worker pools perform task updates, reads, notification reads/mutations, membership revocation, and concurrent task deletion/activity retrieval. Every worker has a timeout; completion, failures, latency distribution, elapsed time, throughput, index consistency, and restart integrity are recorded.

This verifies serialization-based deadlock prevention. Strata does not implement a general deadlock detector. The harness never starts multiple writer processes; a second engine is rejected by the directory lease.

## Interpretation and limitations

Latency is measured with `time.perf_counter_ns()` and reported as minimum, median, nearest-rank p95, and maximum milliseconds. Results are machine-specific observations, not stable performance thresholds. Small-sample ratios must not be used to infer asymptotic complexity.

No comparison with SQLite or PostgreSQL is included because this phase does not establish equivalent durability, cache, schema, and execution settings. The suite makes no claim of ACID compliance, WAL recovery, crash atomicity, multiprocess writer safety, or deadlock detection.
