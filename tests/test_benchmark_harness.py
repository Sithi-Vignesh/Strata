import json

from benchmarks.run import latency_stats, run_suite


def test_latency_stats_are_monotonic_and_use_nearest_rank_p95():
    stats = latency_stats([5_000_000, 1_000_000, 3_000_000, 2_000_000, 4_000_000])
    assert stats == {"minimum": 1.0, "median": 3.0, "p95": 5.0, "maximum": 5.0}


def test_tiny_suite_is_isolated_structured_and_cleans_storage(tmp_path):
    output = tmp_path / "report"
    report = run_suite("smoke", [30], 1, 0, 4, output)
    assert report["status"] == "passed"
    assert report["cleanup"] == {"temporary_root_removed": True}
    assert {item["name"] for item in report["datasets"][0]["workloads"]} >= {
        "full_table_scan", "equality_filter_index", "range_filter_index",
        "order_by_limit", "aggregation", "group_by", "inner_join",
    }
    assert report["datasets"][0]["speedups"]["equality"]["valid"] is True
    assert report["integrity"]["status"] == "passed"
    assert report["concurrency"]["status"] == "passed"
    assert report["compensation"]["status"] == "passed"
    persisted = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert (output / "report.md").read_text(encoding="utf-8").startswith("# Strata Database Benchmark Report")
