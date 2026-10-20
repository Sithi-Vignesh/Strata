"""Isolated SQL benchmarks plus integrity, concurrency, and compensation checks."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import sys
import tempfile
from threading import Barrier
from time import perf_counter, perf_counter_ns
from typing import Any, Callable, Iterable

from strata_backend.product_bootstrap import initialize_product
from strata_backend.product_service import ProductNotFoundError, ProductService
from strata_engine import StrataEngine
from strata_engine.catalog import Table
from strata_engine.result import QueryResult
from strata_engine.schema import Tuple
from strata_engine.storage.b_plus_tree import BPlusTree


SEED = 20_261_019
PROFILES = {
    "smoke": {"sizes": [100, 1_000], "iterations": 3, "warmups": 1, "concurrency_operations": 12},
    "full": {"sizes": [100, 1_000, 5_000], "iterations": 7, "warmups": 2, "concurrency_operations": 30},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--sizes", help="Comma-separated positive row counts overriding the profile")
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--warmups", type=int)
    parser.add_argument("--concurrency-operations", type=int)
    parser.add_argument("--output-dir", type=Path, default=Path(".verification/benchmarks/latest"))
    args = parser.parse_args(argv)
    defaults = PROFILES[args.profile]
    sizes = parse_sizes(args.sizes) if args.sizes else list(defaults["sizes"])
    iterations = positive(args.iterations if args.iterations is not None else defaults["iterations"], "iterations")
    warmups = non_negative(args.warmups if args.warmups is not None else defaults["warmups"], "warmups")
    operations = positive(args.concurrency_operations if args.concurrency_operations is not None else defaults["concurrency_operations"], "concurrency operations")
    try:
        report = run_suite(args.profile, sizes, iterations, warmups, operations, args.output_dir)
    except Exception as exc:
        print(f"Benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"JSON: {report['artifacts']['json']}")
    print(f"Markdown: {report['artifacts']['markdown']}")
    return 0 if report["status"] == "passed" else 1


def run_suite(
    profile: str,
    sizes: list[int],
    iterations: int,
    warmups: int,
    concurrency_operations: int,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    temporary_root = Path(tempfile.mkdtemp(prefix="strata-benchmark-")).resolve()
    assert_safe_temporary_root(temporary_root)
    failures: list[str] = []
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "profile": profile,
        "seed": SEED,
        "configuration": {
            "dataset_sizes": sizes,
            "iterations": iterations,
            "warmup_iterations": warmups,
            "concurrency_operations": concurrency_operations,
            "cache_methodology": "Warm-cache: every query is warmed independently before recorded iterations; indexed and scan tables contain equivalent rows in the same engine.",
        },
        "environment": environment_metadata(),
        "started_at": started.isoformat(),
        "datasets": [],
        "integrity": {},
        "concurrency": {},
        "compensation": {},
        "unsupported": [
            {"category": "join access-path profile", "reason": "The engine intentionally returns no singular scan profile for joins."},
            {"category": "cold-cache comparison", "reason": "The buffer pool has no public deterministic cache-reset API; results are explicitly warm-cache."},
            {"category": "multi-process writers", "reason": "A directory lease rejects a second engine; only single-process concurrency is supported."},
            {"category": "crash/power-loss recovery", "reason": "No WAL or crash-atomicity guarantee exists; only recoverable in-process compensation is tested."},
        ],
        "observations": [
            "The planner chooses the first eligible indexed comparison in an AND predicate. A two-sided range therefore uses one B+ tree bound and applies the other bound as a residual filter.",
            "INNER JOIN uses the engine's nested-loop join implementation and intentionally has no singular access-path profile.",
        ],
        "failures": failures,
    }
    try:
        for size in sizes:
            dataset_dir = temporary_root / f"sql-{size}"
            report["datasets"].append(run_sql_dataset(dataset_dir, size, iterations, warmups))
        report["integrity"] = run_integrity(temporary_root / "integrity")
        report["concurrency"] = run_concurrency(temporary_root / "concurrency", concurrency_operations)
        report["compensation"] = run_compensation(temporary_root / "compensation")
        for section in (report["integrity"], report["concurrency"], report["compensation"]):
            if section.get("status") != "passed":
                failures.extend(section.get("failures", [f"{section.get('name', 'section')} failed"]))
        report["status"] = "passed" if not failures else "failed"
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}")
        report["status"] = "failed"
        raise
    finally:
        assert_safe_temporary_root(temporary_root)
        shutil.rmtree(temporary_root)
        report["cleanup"] = {"temporary_root_removed": not temporary_root.exists()}
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["elapsed_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 6)
        json_path = output_dir / "results.json"
        markdown_path = output_dir / "report.md"
        report["artifacts"] = {"json": str(json_path), "markdown": str(markdown_path)}
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return report


def run_sql_dataset(directory: Path, size: int, iterations: int, warmups: int) -> dict[str, Any]:
    rng = random.Random(SEED + size)
    setup_start = perf_counter_ns()
    with StrataEngine(directory) as engine:
        for table in ("scan_items", "index_items"):
            engine.execute(f"CREATE TABLE {table} (id INTEGER, category INTEGER, score INTEGER, payload VARCHAR(96));")
        engine.execute("CREATE TABLE categories (id INTEGER, label VARCHAR(32));")
        categories = engine.get_table("categories")
        for category in range(10):
            categories.insert((category, f"category-{category}"))
        scan_table, index_table = engine.get_table("scan_items"), engine.get_table("index_items")
        rows = []
        for logical_id in range(size):
            row = (logical_id, logical_id % 10, rng.randrange(0, max(size, 100)), f"payload-{logical_id % 97:02d}")
            rows.append(row)
            scan_table.insert(row)
            index_table.insert(row)
        setup_ms = ns_to_ms(perf_counter_ns() - setup_start)
        build_start = perf_counter_ns()
        engine.create_index("index_items_id", "index_items", "id")
        index_build_ms = ns_to_ms(perf_counter_ns() - build_start)
        target = size // 2
        lower, upper = size // 3, size // 3 + max(5, size // 20)
        workloads = [
            ("full_table_scan", "SELECT * FROM scan_items;", "TableScan"),
            ("equality_filter_scan", f"SELECT id, category, score, payload FROM scan_items WHERE id = {target};", "TableScan"),
            ("equality_filter_index", f"SELECT id, category, score, payload FROM index_items WHERE id = {target};", "IndexScan"),
            ("range_filter_scan", f"SELECT id, score FROM scan_items WHERE id >= {lower} AND id <= {upper};", "TableScan"),
            ("range_filter_index", f"SELECT id, score FROM index_items WHERE id >= {lower} AND id <= {upper};", "IndexScan"),
            ("order_by_limit", "SELECT id, score FROM scan_items ORDER BY score DESC, id ASC LIMIT 25;", "TableScan"),
            ("limit", "SELECT id, payload FROM scan_items LIMIT 25;", "TableScan"),
            ("aggregation", "SELECT COUNT(*), SUM(score), AVG(score), MIN(score), MAX(score) FROM scan_items;", "TableScan"),
            ("group_by", "SELECT category, COUNT(*), AVG(score) FROM scan_items GROUP BY category ORDER BY category;", "TableScan"),
            ("inner_join", "SELECT scan_items.id, categories.label FROM scan_items INNER JOIN categories ON scan_items.category = categories.id;", None),
        ]
        measured = []
        results: dict[str, tuple[tuple[object, ...], ...]] = {}
        for name, query, expected_path in workloads:
            item, rows_result = measure_query(engine, name, query, iterations, warmups, expected_path)
            measured.append(item)
            results[name] = rows_result
        if results["equality_filter_scan"] != results["equality_filter_index"]:
            raise AssertionError("Indexed and non-indexed equality results differ.")
        if results["range_filter_scan"] != results["range_filter_index"]:
            raise AssertionError("Indexed and non-indexed range results differ.")
        index_consistency = verify_indexes(engine)
        speedups = {
            "equality": speedup(measured, "equality_filter_scan", "equality_filter_index"),
            "range": speedup(measured, "range_filter_scan", "range_filter_index"),
        }
    with StrataEngine(directory) as reopened:
        persisted = reopened.get_table("scan_items").count() == size and reopened.get_table("index_items").count() == size
        reopened_indexes = verify_indexes(reopened)
    if not persisted:
        raise AssertionError("Dataset counts did not persist after restart.")
    return {
        "size": size,
        "setup_ms": setup_ms,
        "index_build_ms": index_build_ms,
        "workloads": measured,
        "speedups": speedups,
        "index_consistency": index_consistency,
        "restart": {"counts_persisted": persisted, "index_consistency": reopened_indexes},
    }


def measure_query(
    engine: StrataEngine,
    name: str,
    query: str,
    iterations: int,
    warmups: int,
    expected_path: str | None,
) -> tuple[dict[str, Any], tuple[tuple[object, ...], ...]]:
    for _ in range(warmups):
        engine.execute(query)
    durations = []
    last: QueryResult | None = None
    for _ in range(iterations):
        started = perf_counter_ns()
        result = engine.execute(query)
        durations.append(perf_counter_ns() - started)
        if not isinstance(result, QueryResult):
            raise AssertionError(f"{name} did not return rows.")
        last = result
    assert last is not None
    profiled = engine.execute_profiled(query)
    profile = None if profiled.profile is None else asdict(profiled.profile)
    if expected_path is not None and (profile is None or profile["access_path"] != expected_path):
        raise AssertionError(f"{name} expected {expected_path}, observed {profile}.")
    values = tuple(row.values for row in last.rows)
    return {
        "name": name,
        "query": query,
        "iterations": iterations,
        "warmups": warmups,
        "result_rows": len(values),
        "latency_ms": latency_stats(durations),
        "profile": profile,
    }, values


def run_integrity(directory: Path) -> dict[str, Any]:
    storage_dir = directory / "storage"
    product_dir = directory / "product"
    expected: dict[int, tuple[object, ...]] = {}
    with StrataEngine(storage_dir) as engine:
        engine.execute("CREATE TABLE integrity_items (id INTEGER, tag VARCHAR(32), payload VARCHAR(160));")
        engine.create_index("integrity_id", "integrity_items", "id")
        engine.create_index("integrity_tag", "integrity_items", "tag")
        table = engine.get_table("integrity_items")
        for logical_id in range(240):
            row = (logical_id, f"tag-{logical_id % 13}", "x" * (20 + logical_id % 120))
            table.insert(row)
            expected[logical_id] = row
        for rid, stored_row in list(table.scan()):
            logical_id = int(stored_row[0])
            if logical_id % 11 == 0:
                replacement = (logical_id, f"updated-{logical_id % 7}", "y" * 150)
                table.update(rid, Tuple(replacement, table.schema))
                expected[logical_id] = replacement
        by_id = {row[0]: rid for rid, row in table.scan()}
        for logical_id in sorted(tuple(expected)):
            if logical_id % 9 == 0:
                table.delete(by_id[logical_id])
                del expected[logical_id]
        assert_table_matches(table, expected)
        before_restart = verify_indexes(engine)
    with StrataEngine(storage_dir) as reopened:
        table = reopened.get_table("integrity_items")
        assert_table_matches(table, expected)
        after_restart = verify_indexes(reopened)
    with StrataEngine(product_dir) as engine:
        initialize_product(engine)
        service = ProductService(engine)
        owner = service.create_user("Integrity owner", "integrity-owner@example.test")
        outsider = service.create_user("Integrity outsider", "integrity-outsider@example.test")
        workspace = service.create_workspace("Integrity team", owner.id)
        private_workspace = service.create_workspace("Outsider private", outsider.id)
        project = service.create_project(workspace.id, "Integrity project", actor_user_id=owner.id)
        task = service.create_task(project.id, "Cascade task", due_date="2030-01-15", actor_user_id=owner.id)
        service.create_note(task.id, owner.id, "Cascade note", actor_user_id=owner.id)
        try:
            service.get_workspace(private_workspace.id, actor_user_id=owner.id)
        except ProductNotFoundError:
            cross_workspace_hidden = True
        else:
            cross_workspace_hidden = False
        service.delete_task(task.id, actor_user_id=owner.id)
        orphan_notes = sum(1 for _, row in engine.get_table("notes").scan() if row[1] == task.id)
        orphan_due_dates = sum(1 for _, row in engine.get_table("task_due_dates").scan() if row[0] == task.id)
        retained_history = sum(1 for _, row in engine.get_table("task_activity").scan() if row[1] == task.id)
        if not cross_workspace_hidden or orphan_notes or orphan_due_dates or retained_history == 0:
            raise AssertionError("Product isolation or task sidecar cascade verification failed.")
        product_indexes = verify_indexes(engine)
    return {
        "name": "storage_and_index_integrity",
        "status": "passed",
        "inserted": 240,
        "remaining": len(expected),
        "updated": len([item for item in range(240) if item % 11 == 0]),
        "deleted": 240 - len(expected),
        "duplicates": 0,
        "before_restart": before_restart,
        "after_restart": after_restart,
        "cross_workspace_hidden": cross_workspace_hidden,
        "orphan_notes": orphan_notes,
        "orphan_due_dates": orphan_due_dates,
        "retained_audit_history_rows": retained_history,
        "product_indexes": product_indexes,
    }


def run_concurrency(directory: Path, operation_count: int) -> dict[str, Any]:
    with StrataEngine(directory) as engine:
        initialize_product(engine)
        services = [ProductService(engine) for _ in range(4)]
        owner = services[0].create_user("Benchmark owner", "benchmark-owner@example.test")
        member = services[0].create_user("Benchmark member", "benchmark-member@example.test")
        workspace = services[0].create_workspace("Benchmark team", owner.id)
        services[0].add_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
        project = services[0].create_project(workspace.id, "Concurrent project", actor_user_id=owner.id)
        task = services[0].create_task(project.id, "Shared task", assignee_user_id=member.id, actor_user_id=owner.id)
        delete_task = services[0].create_task(project.id, "Delete race", actor_user_id=owner.id)
        gate = Barrier(5, timeout=8)
        actions: list[tuple[str, Callable[[], object]]] = []
        for index in range(operation_count):
            service = services[index % len(services)]
            mode = index % 4
            if mode == 0:
                actions.append(("task_update", lambda s=service, n=index: s.update_task(task.id, title=f"Shared task {n}", actor_user_id=owner.id)))
            elif mode == 1:
                actions.append(("task_read", lambda s=service: s.get_task(task.id, actor_user_id=member.id)))
            elif mode == 2:
                actions.append(("notification_read", lambda s=service: s.list_notifications(actor_user_id=member.id)))
            else:
                actions.append(("notification_mutation", lambda s=service: s.mark_all_notifications_read(actor_user_id=member.id)))
        chunks = [actions[index::4] for index in range(4)]
        def worker(chunk: list[tuple[str, Callable[[], object]]]) -> list[dict[str, Any]]:
            gate.wait()
            outcomes = []
            for label, action in chunk:
                start = perf_counter_ns()
                try:
                    action()
                    outcomes.append({"label": label, "success": True, "ns": perf_counter_ns() - start})
                except Exception as exc:
                    outcomes.append({"label": label, "success": False, "ns": perf_counter_ns() - start, "error": f"{type(exc).__name__}: {exc}"})
            return outcomes
        started = perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker, chunk) for chunk in chunks]
            gate.wait()
            outcomes = [item for future in futures for item in future.result(timeout=20)]
        elapsed = perf_counter() - started
        # Membership revocation and task deletion/activity retrieval are separate,
        # bounded two-worker races whose valid outcomes do not depend on ordering.
        revocation = bounded_pair(
            lambda: services[0].remove_workspace_member(workspace.id, member.id, actor_user_id=owner.id),
            lambda: services[1].list_workspaces_for_user(member.id, actor_user_id=member.id),
        )
        deletion = bounded_pair(
            lambda: services[0].delete_task(delete_task.id, actor_user_id=owner.id),
            lambda: services[1].list_task_activity(delete_task.id, actor_user_id=owner.id),
        )
        member_workspaces = services[0].list_workspaces_for_user(member.id, actor_user_id=member.id)
        member_removed = all(item.id != workspace.id for item in member_workspaces)
        assignment_cleared = services[0].get_task(task.id, actor_user_id=owner.id).assignee_user_id is None
        if not member_removed or not assignment_cleared:
            raise AssertionError("Membership revocation left access or an outside assignee.")
        failures = [item for item in outcomes if not item["success"]]
        latencies = [item["ns"] for item in outcomes]
        indexes = verify_indexes(engine)
    with StrataEngine(directory) as reopened:
        persisted_indexes = verify_indexes(reopened)
    return {
        "name": "single_process_serialized_workload",
        "status": "passed" if not failures and all(item["success"] for item in revocation + deletion) else "failed",
        "operation_count": len(outcomes) + len(revocation) + len(deletion),
        "mixed_successes": len(outcomes) - len(failures),
        "mixed_failures": len(failures),
        "elapsed_seconds": round(elapsed, 6),
        "throughput_operations_per_second": round(len(outcomes) / elapsed, 3),
        "mixed_latency_ms": latency_stats(latencies),
        "membership_revocation_race": revocation,
        "task_deletion_activity_race": deletion,
        "member_access_revoked": member_removed,
        "revoked_assignee_cleared": assignment_cleared,
        "indexes": indexes,
        "indexes_after_restart": persisted_indexes,
        "failures": [item.get("error", "operation failed") for item in failures],
        "claim": "bounded completion under serialization-based deadlock prevention; no deadlock detector is claimed",
    }


def run_compensation(directory: Path) -> dict[str, Any]:
    storage_dir = directory / "storage"
    product_dir = directory / "product"
    with StrataEngine(storage_dir) as engine:
        engine.execute("CREATE TABLE compensated (id INTEGER, tag VARCHAR(32));")
        engine.create_index("compensated_id", "compensated", "id")
        engine.create_index("compensated_tag", "compensated", "tag")
        table = engine.get_table("compensated")
        table.insert((1, "old"))
        before = snapshot_table(table)
        target = table.indexes[1].tree
        original_insert = BPlusTree.insert
        failed = False
        def fail_once(tree: BPlusTree, key: object, record_id: object) -> bool:
            nonlocal failed
            if tree is target and not failed:
                failed = True
                raise OSError("controlled index maintenance failure")
            return original_insert(tree, key, record_id)  # type: ignore[arg-type]
        BPlusTree.insert = fail_once  # type: ignore[method-assign]
        try:
            try:
                table.insert((2, "new"))
            except OSError as exc:
                if "controlled index maintenance failure" not in str(exc):
                    raise
            else:
                raise AssertionError("Controlled index failure was not raised.")
        finally:
            BPlusTree.insert = original_insert  # type: ignore[method-assign]
        if snapshot_table(table) != before:
            raise AssertionError("Storage compensation did not restore the row snapshot.")
        verify_indexes(engine)
    with StrataEngine(storage_dir) as reopened:
        if snapshot_table(reopened.get_table("compensated")) != before:
            raise AssertionError("Compensated storage state did not persist.")
        verify_indexes(reopened)

    with StrataEngine(product_dir) as engine:
        initialize_product(engine)
        service = ProductService(engine)
        owner = service.create_user("Compensation owner", "compensation-owner@example.test")
        member = service.create_user("Compensation member", "compensation-member@example.test")
        workspace = service.create_workspace("Compensation", owner.id)
        service.add_workspace_member(workspace.id, member.id, actor_user_id=owner.id)
        project = service.create_project(workspace.id, "Project", actor_user_id=owner.id)
        task = service.create_task(project.id, "Original", assignee_user_id=member.id, actor_user_id=owner.id)
        activity_before = engine.get_table("task_activity").count()
        notifications_before = engine.get_table("notifications").count()
        original_table_insert = Table.insert
        failed_activity = False
        def fail_activity(target_table: Table, row: object) -> object:
            nonlocal failed_activity
            if target_table.name == "task_activity" and not failed_activity:
                failed_activity = True
                raise OSError("controlled activity failure")
            return original_table_insert(target_table, row)  # type: ignore[arg-type]
        Table.insert = fail_activity  # type: ignore[method-assign]
        try:
            try:
                service.update_task(task.id, status="DONE", actor_user_id=owner.id)
            except OSError as exc:
                if "controlled activity failure" not in str(exc):
                    raise
            else:
                raise AssertionError("Controlled activity failure was not raised.")
        finally:
            Table.insert = original_table_insert  # type: ignore[method-assign]
        restored = service.get_task(task.id, actor_user_id=owner.id)
        if restored.status != "TODO":
            raise AssertionError("Task update compensation did not restore the original status.")
        if engine.get_table("task_activity").count() != activity_before:
            raise AssertionError("A failed mutation left false activity records.")
        if engine.get_table("notifications").count() != notifications_before:
            raise AssertionError("A failed mutation left false notifications.")
        verify_indexes(engine)
    return {
        "name": "recoverable_failure_compensation",
        "status": "passed",
        "storage_index_failure_restored": True,
        "storage_restart_verified": True,
        "product_task_state_restored": True,
        "false_activity_records": 0,
        "false_notification_records": 0,
        "limitation": "In-process best-effort compensation only; no crash atomicity or WAL recovery claim.",
    }


def bounded_pair(first: Callable[[], object], second: Callable[[], object]) -> list[dict[str, Any]]:
    gate = Barrier(3, timeout=8)
    def run(label: str, action: Callable[[], object]) -> dict[str, Any]:
        gate.wait()
        started = perf_counter_ns()
        try:
            action()
            return {"label": label, "success": True, "latency_ms": ns_to_ms(perf_counter_ns() - started)}
        except Exception as exc:
            return {"label": label, "success": False, "latency_ms": ns_to_ms(perf_counter_ns() - started), "error": f"{type(exc).__name__}: {exc}"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, "first", first), pool.submit(run, "second", second)]
        gate.wait()
        return [future.result(timeout=12) for future in futures]


def verify_indexes(engine: StrataEngine) -> dict[str, int]:
    tables = indexes = entries = 0
    with engine.operation():
        for name in engine.list_tables():
            table = engine.get_table(name)
            rows = tuple(table.scan())
            tables += 1
            for index in table.indexes:
                expected = {(row[index.column_ordinal], rid) for rid, row in rows if row[index.column_ordinal] is not None}
                actual = index.tree.scan_range()
                if set(actual) != expected or len(actual) != len(expected) or len(actual) != index.tree.entry_count:
                    raise AssertionError(f"Index '{index.name}' does not match table '{name}'.")
                index.tree.validate_structure()
                if any(frame.pin_count != 0 for frame in index.tree._buffer_pool._frames):
                    raise AssertionError(f"Index '{index.name}' leaked pinned frames.")
                indexes += 1
                entries += len(actual)
            if any(frame.pin_count != 0 for frame in table.heap_file.buffer_pool_manager._frames):
                raise AssertionError(f"Table '{name}' leaked pinned frames.")
    return {"tables_checked": tables, "indexes_checked": indexes, "index_entries_checked": entries}


def assert_table_matches(table: Table, expected: dict[int, tuple[object, ...]]) -> None:
    rows = [row.values for _, row in table.scan()]
    actual = {int(row[0]): row for row in rows}
    if len(actual) != len(rows):
        raise AssertionError("Unexpected duplicate logical IDs detected.")
    if actual != expected:
        raise AssertionError("Table records differ from the deterministic expected model.")


def snapshot_table(table: Table) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted((row.values for _, row in table.scan()), key=repr))


def speedup(workloads: list[dict[str, Any]], baseline: str, indexed: str) -> dict[str, Any]:
    base = next(item for item in workloads if item["name"] == baseline)
    candidate = next(item for item in workloads if item["name"] == indexed)
    baseline_ms = base["latency_ms"]["median"]
    indexed_ms = candidate["latency_ms"]["median"]
    valid = base["profile"]["access_path"] == "TableScan" and candidate["profile"]["access_path"] == "IndexScan"
    return {
        "baseline": baseline,
        "indexed": indexed,
        "valid": valid,
        "ratio": None if not valid or indexed_ms == 0 else round(baseline_ms / indexed_ms, 3),
    }


def latency_stats(durations_ns: Iterable[int]) -> dict[str, float]:
    values = sorted(durations_ns)
    if not values:
        raise ValueError("At least one duration is required.")
    p95_index = max(0, math.ceil(len(values) * 0.95) - 1)
    return {
        "minimum": ns_to_ms(values[0]),
        "median": ns_to_ms(int(statistics.median(values))),
        "p95": ns_to_ms(values[p95_index]),
        "maximum": ns_to_ms(values[-1]),
    }


def environment_metadata() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unavailable",
        "logical_cpu_count": os.cpu_count(),
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strata Database Benchmark Report",
        "",
        f"- Status: **{report['status']}**",
        f"- Profile: `{report['profile']}`",
        f"- Seed: `{report['seed']}`",
        f"- Python: `{report['environment']['python']}`",
        f"- OS: `{report['environment']['operating_system']}`",
        f"- Iterations/warmups: {report['configuration']['iterations']}/{report['configuration']['warmup_iterations']}",
        "",
        "## SQL workload results",
        "",
        "| Rows | Workload | Access path | Median ms | p95 ms | Result rows |",
        "| ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for dataset in report["datasets"]:
        for workload in dataset["workloads"]:
            path = "unprofiled" if workload["profile"] is None else workload["profile"]["access_path"]
            lines.append(f"| {dataset['size']} | {workload['name']} | {path} | {workload['latency_ms']['median']:.3f} | {workload['latency_ms']['p95']:.3f} | {workload['result_rows']} |")
        lines.extend([
            "",
        f"Dataset {dataset['size']}: setup {dataset['setup_ms']:.3f} ms; index build {dataset['index_build_ms']:.3f} ms; equality ratio {dataset['speedups']['equality']['ratio']}x; range ratio {dataset['speedups']['range']['ratio']}x.",
            "",
        ])
    concurrency = report.get("concurrency", {})
    lines.extend([
        "## Correctness evidence",
        "",
        f"- Integrity: **{report.get('integrity', {}).get('status', 'not run')}**",
        f"- Concurrency: **{concurrency.get('status', 'not run')}**; {concurrency.get('operation_count', 0)} operations; {concurrency.get('throughput_operations_per_second', 0)} mixed operations/s.",
        f"- Compensation: **{report.get('compensation', {}).get('status', 'not run')}**",
        f"- Temporary storage removed: `{report.get('cleanup', {}).get('temporary_root_removed', False)}`",
        "",
        "## Limitations",
        "",
    ])
    lines.extend(f"- **{item['category']}**: {item['reason']}" for item in report["unsupported"])
    lines.extend(["", "## Observations", ""])
    lines.extend(f"- {item}" for item in report["observations"])
    lines.extend([
        "",
        "Absolute timings are machine-specific observations, not regression thresholds. Ratios are reported only after result equivalence and actual TableScan/IndexScan paths are verified.",
        "",
    ])
    return "\n".join(lines)


def assert_safe_temporary_root(path: Path) -> None:
    temp = Path(tempfile.gettempdir()).resolve()
    if path.parent != temp or not path.name.startswith("strata-benchmark-"):
        raise RuntimeError(f"Refusing destructive benchmark work outside a verified temporary root: {path}")


def parse_sizes(value: str) -> list[int]:
    try:
        sizes = [positive(int(item.strip()), "dataset size") for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not sizes:
        raise argparse.ArgumentTypeError("At least one dataset size is required.")
    return sizes


def positive(value: int, label: str) -> int:
    if value <= 0:
        raise ValueError(f"{label} must be positive.")
    return value


def non_negative(value: int, label: str) -> int:
    if value < 0:
        raise ValueError(f"{label} must not be negative.")
    return value


def ns_to_ms(value: int) -> float:
    return round(value / 1_000_000, 6)


if __name__ == "__main__":
    raise SystemExit(main())
