"""Comprehensive tests for Strata relational execution layer (Phase 6).

Covers:
- Operator lifecycle: state transitions, open, next, EOF, close, rewind, and error handling.
- TableScan: logical tuple streaming, borrowing Table, RecordId stripping, empty tables,
  closed table handling, and buffer pool unpinning.
- Predicates: ComparisonPredicate (operators, normalization, NULL safety, type validation),
  IsNullPredicate, immutability, and strict bool returns.
- Filter: predicate filtering, plan-time validation, schema preservation, child cascading.
- Projection: column subsetting, reordering, duplicate column rejection, schema fingerprints,
  bound output tuples.
- Pipelines: end-to-end combinations (Projection -> Filter -> TableScan).
- Error propagation and exception preservation during open() and next().
- Context manager and Python iteration conveniences without double-open or rewinds.
"""

from pathlib import Path
import pytest

from strata_engine.catalog.table import Table
from strata_engine.execution import (
    ComparisonPredicate,
    ExecutionError,
    Filter,
    IsNullPredicate,
    OperatorClosedError,
    Projection,
    TableScan,
)
from strata_engine.schema import (
    Column,
    ColumnNotFoundError,
    DataType,
    DuplicateColumnError,
    Schema,
    Tuple,
    TypeMismatchError,
)
from strata_engine.storage import (
    BufferPoolManager,
    HeapFile,
    PageFile,
    StorageClosedError,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_schema() -> Schema:
    return Schema([
        Column("id", DataType.INTEGER, nullable=False),
        Column("name", DataType.VARCHAR, nullable=False, max_length=50),
        Column("score", DataType.FLOAT, nullable=True),
        Column("active", DataType.BOOLEAN, nullable=False),
    ])


@pytest.fixture
def populated_table(tmp_path: Path, sample_schema: Schema):
    """Provide an open Table populated with 5 deterministic test rows."""
    db_file = tmp_path / "test_exec.db"
    pf = PageFile(db_file)
    bpm = BufferPoolManager(pf, pool_size=5)
    hf = HeapFile(bpm)
    tbl = Table(1, "users", sample_schema, hf)

    tbl.insert([1, "Alice", 95.5, True])
    tbl.insert([2, "Bob", 80.0, False])
    tbl.insert([3, "Charlie", None, True])
    tbl.insert([4, "Diana", 65.2, False])
    tbl.insert([5, "Eve", 90.0, True])

    yield tbl, sample_schema
    tbl.close()


@pytest.fixture
def empty_table(tmp_path: Path, sample_schema: Schema):
    """Provide an open Table with zero records."""
    db_file = tmp_path / "empty_exec.db"
    pf = PageFile(db_file)
    bpm = BufferPoolManager(pf, pool_size=5)
    hf = HeapFile(bpm)
    tbl = Table(2, "empty_tbl", sample_schema, hf)
    yield tbl, sample_schema
    tbl.close()


# ============================================================================
# 1. Operator Lifecycle Tests
# ============================================================================


def test_operator_lifecycle_states(populated_table) -> None:
    """Verify operator state machine: UNINITIALIZED -> ACTIVE -> EXHAUSTED -> CLOSED."""
    tbl, _ = populated_table
    scan = TableScan(tbl)

    # UNINITIALIZED: schema available, is_open is False, next() raises
    assert scan.schema is tbl.schema
    assert scan.is_open is False
    with pytest.raises(OperatorClosedError):
        scan.next()

    # Transition to ACTIVE
    scan.open()
    assert scan.is_open is True

    # Fetch rows
    rows = []
    while (row := scan.next()) is not None:
        rows.append(row)
    assert len(rows) == 5

    # EXHAUSTED: subsequent next() calls continue returning None
    assert scan.next() is None
    assert scan.next() is None

    # Transition to CLOSED
    scan.close()
    assert scan.is_open is False

    # CLOSED: next() raises OperatorClosedError
    with pytest.raises(OperatorClosedError):
        scan.next()

    # Repeated close is idempotent
    scan.close()
    scan.close()
    assert scan.is_open is False


def test_operator_rewind_and_reopen(populated_table) -> None:
    """Verify open() rewinds an operator from ACTIVE, EXHAUSTED, or CLOSED."""
    tbl, _ = populated_table
    scan = TableScan(tbl)

    # Partial read then rewind while ACTIVE
    scan.open()
    assert scan.next()["id"] == 1
    assert scan.next()["id"] == 2
    scan.open()  # Rewind
    assert scan.next()["id"] == 1

    # Read to exhaustion
    for _ in range(4):
        scan.next()
    assert scan.next() is None  # EXHAUSTED

    # Rewind from EXHAUSTED
    scan.open()
    assert scan.next()["id"] == 1

    # Close and reopen from CLOSED
    scan.close()
    assert scan.is_open is False
    scan.open()
    assert scan.is_open is True
    assert scan.next()["id"] == 1
    scan.close()


# ============================================================================
# 2. TableScan Tests
# ============================================================================


def test_table_scan_empty_table(empty_table) -> None:
    """Verify TableScan over an empty table returns None immediately."""
    tbl, _ = empty_table
    scan = TableScan(tbl)
    scan.open()
    assert scan.next() is None
    assert scan.next() is None
    scan.close()


def test_table_scan_tuple_properties_and_no_record_id(populated_table) -> None:
    """Verify TableScan yields schema-bound Tuples without exposing RecordId."""
    tbl, schema = populated_table
    scan = TableScan(tbl)
    scan.open()
    row = scan.next()
    assert isinstance(row, Tuple)
    assert row.schema is schema
    assert row["name"] == "Alice"
    assert row["id"] == 1
    assert row[2] == 95.5
    scan.close()


def test_table_scan_does_not_close_table(populated_table) -> None:
    """Verify TableScan.close() does NOT close the underlying borrowed Table."""
    tbl, _ = populated_table
    scan = TableScan(tbl)
    scan.open()
    scan.next()
    scan.close()

    assert scan.is_open is False
    assert tbl.is_closed is False
    # Table remains usable
    assert tbl.count() == 5


def test_table_scan_closed_table_raises(populated_table) -> None:
    """Verify TableScan.open() on a closed table raises StorageClosedError."""
    tbl, _ = populated_table
    tbl.close()
    scan = TableScan(tbl)

    with pytest.raises(StorageClosedError):
        scan.open()


# ============================================================================
# 3. Predicate Unit Tests
# ============================================================================


def test_comparison_predicate_operators(sample_schema) -> None:
    """Verify comparison operators and == normalization."""
    # Equality with = and ==
    p1 = ComparisonPredicate("id", "=", 3)
    p2 = ComparisonPredicate("id", "==", 3)
    assert p1.op == "="
    assert p2.op == "="

    p1.validate(sample_schema)
    p2.validate(sample_schema)

    row = Tuple([3, "Charlie", 70.0, True], schema=sample_schema)
    assert p1.evaluate(row) is True
    assert p2.evaluate(row) is True

    # Other operators
    p_neq = ComparisonPredicate("id", "!=", 3)
    p_diamond = ComparisonPredicate("id", "<>", 3)
    p_lt = ComparisonPredicate("id", "<", 3)
    p_lte = ComparisonPredicate("id", "<=", 3)
    p_gt = ComparisonPredicate("id", ">", 3)
    p_gte = ComparisonPredicate("id", ">=", 3)

    assert p_neq.evaluate(row) is False
    assert p_diamond.evaluate(row) is False
    assert p_lt.evaluate(row) is False
    assert p_lte.evaluate(row) is True
    assert p_gt.evaluate(row) is False
    assert p_gte.evaluate(row) is True


def test_comparison_predicate_invalid_construction() -> None:
    """Verify invalid constructor arguments raise appropriate exceptions."""
    # literal is None
    with pytest.raises(ValueError) as exc:
        ComparisonPredicate("score", "=", None)
    assert "cannot be None" in str(exc.value)

    # unsupported operator
    with pytest.raises(ValueError) as exc:
        ComparisonPredicate("id", "LIKE", 1)
    assert "Unsupported comparison operator" in str(exc.value)

    # non-str column_name
    with pytest.raises(TypeError):
        ComparisonPredicate(123, "=", 1)  # type: ignore[arg-type]


def test_comparison_predicate_validation(sample_schema) -> None:
    """Verify plan-time type compatibility validation rules."""
    # Missing column
    p_missing = ComparisonPredicate("nonexistent", "=", 10)
    with pytest.raises(ColumnNotFoundError):
        p_missing.validate(sample_schema)

    # INTEGER column rejects str literal
    p_bad_int = ComparisonPredicate("id", "=", "10")
    with pytest.raises(TypeMismatchError):
        p_bad_int.validate(sample_schema)

    # INTEGER rejects bool literal
    p_bool_as_int = ComparisonPredicate("id", "=", True)
    with pytest.raises(TypeMismatchError):
        p_bool_as_int.validate(sample_schema)

    # FLOAT accepts float literal
    p_float = ComparisonPredicate("score", ">", 80.5)
    p_float.validate(sample_schema)

    # FLOAT accepts int literal in execution layer
    p_int_as_float = ComparisonPredicate("score", ">", 80)
    p_int_as_float.validate(sample_schema)

    # FLOAT rejects bool literal
    p_bool_as_float = ComparisonPredicate("score", ">", True)
    with pytest.raises(TypeMismatchError):
        p_bool_as_float.validate(sample_schema)

    # BOOLEAN requires bool
    p_bool = ComparisonPredicate("active", "=", True)
    p_bool.validate(sample_schema)

    p_bad_bool = ComparisonPredicate("active", "=", 1)
    with pytest.raises(TypeMismatchError):
        p_bad_bool.validate(sample_schema)

    # VARCHAR requires str
    p_str = ComparisonPredicate("name", "=", "Alice")
    p_str.validate(sample_schema)

    p_bad_str = ComparisonPredicate("name", "=", 123)
    with pytest.raises(TypeMismatchError):
        p_bad_str.validate(sample_schema)


def test_comparison_predicate_null_semantics(sample_schema) -> None:
    """Verify comparisons with None strictly evaluate to False."""
    row_null = Tuple([1, "NullRow", None, True], schema=sample_schema)

    # All operators against None return False without TypeError
    for op in ("=", "!=", "<>", "<", "<=", ">", ">="):
        pred = ComparisonPredicate("score", op, 80.0)
        res = pred.evaluate(row_null)
        assert res is False
        assert type(res) is bool


def test_is_null_predicate(sample_schema) -> None:
    """Verify IsNullPredicate evaluates IS NULL and IS NOT NULL."""
    p_is_null = IsNullPredicate("score", is_not_null=False)
    p_is_not_null = IsNullPredicate("score", is_not_null=True)

    p_is_null.validate(sample_schema)
    p_is_not_null.validate(sample_schema)

    row_with_val = Tuple([1, "Alice", 95.0, True], schema=sample_schema)
    row_with_null = Tuple([2, "Bob", None, False], schema=sample_schema)

    assert p_is_null.evaluate(row_with_null) is True
    assert p_is_null.evaluate(row_with_val) is False

    assert p_is_not_null.evaluate(row_with_val) is True
    assert p_is_not_null.evaluate(row_with_null) is False

    # Missing column raises ColumnNotFoundError
    with pytest.raises(ColumnNotFoundError):
        IsNullPredicate("missing").validate(sample_schema)


# ============================================================================
# 4. Filter Operator Tests
# ============================================================================


def test_filter_matching_and_selective(populated_table) -> None:
    """Verify Filter accurately filters rows and preserves schema."""
    tbl, schema = populated_table
    scan = TableScan(tbl)
    pred = ComparisonPredicate("score", ">", 85.0)
    flt = Filter(scan, pred)

    # Schema is preserved
    assert flt.schema is schema

    flt.open()
    results = []
    while (r := flt.next()) is not None:
        results.append(r["name"])
    flt.close()

    # Alice (95.5) and Eve (90.0)
    assert results == ["Alice", "Eve"]


def test_filter_matches_none(populated_table) -> None:
    """Verify Filter returning zero rows returns None on next()."""
    tbl, _ = populated_table
    scan = TableScan(tbl)
    pred = ComparisonPredicate("id", ">", 100)
    flt = Filter(scan, pred)

    flt.open()
    assert flt.next() is None
    flt.close()


def test_filter_plan_time_validation_fails(populated_table) -> None:
    """Verify Filter construction triggers predicate validation immediately."""
    tbl, _ = populated_table
    scan = TableScan(tbl)

    # Invalid column
    with pytest.raises(ColumnNotFoundError):
        Filter(scan, ComparisonPredicate("ghost_col", "=", 1))

    # Incompatible literal type
    with pytest.raises(TypeMismatchError):
        Filter(scan, ComparisonPredicate("id", "=", "not_an_int"))


def test_filter_cascading_close(populated_table) -> None:
    """Verify closing Filter cascades close to child operator."""
    tbl, _ = populated_table
    scan = TableScan(tbl)
    flt = Filter(scan, ComparisonPredicate("id", "=", 1))

    flt.open()
    assert flt.is_open is True
    assert scan.is_open is True

    flt.close()
    assert flt.is_open is False
    assert scan.is_open is False


# ============================================================================
# 5. Projection Operator Tests
# ============================================================================


def test_projection_subset_and_reorder(populated_table) -> None:
    """Verify Projection extracts requested subset in specified order."""
    tbl, _ = populated_table
    scan = TableScan(tbl)
    proj = Projection(scan, ["name", "id"])

    # Output schema reflects requested subset and order
    assert proj.schema.column_names == ("name", "id")
    assert proj.schema.column_count == 2
    assert proj.schema[0].data_type == DataType.VARCHAR
    assert proj.schema[1].data_type == DataType.INTEGER

    proj.open()
    row = proj.next()
    assert row["name"] == "Alice"
    assert row["id"] == 1
    assert row.values == ("Alice", 1)
    assert row.schema is proj.schema
    proj.close()


def test_projection_duplicate_columns_rejected(populated_table) -> None:
    """Verify duplicate projected column names raise DuplicateColumnError."""
    tbl, _ = populated_table
    scan = TableScan(tbl)

    with pytest.raises(DuplicateColumnError):
        Projection(scan, ["id", "id"])

    with pytest.raises(DuplicateColumnError):
        Projection(scan, ["Id", "id"])


def test_projection_invalid_columns(populated_table) -> None:
    """Verify missing column or invalid column counts raise errors."""
    tbl, _ = populated_table
    scan = TableScan(tbl)

    # Missing column
    with pytest.raises(ColumnNotFoundError):
        Projection(scan, ["id", "nonexistent"])

    # Zero columns
    with pytest.raises(ValueError):
        Projection(scan, [])


def test_projection_cascading_close(populated_table) -> None:
    """Verify closing Projection cascades to child."""
    tbl, _ = populated_table
    scan = TableScan(tbl)
    proj = Projection(scan, ["id"])

    proj.open()
    assert proj.is_open is True
    assert scan.is_open is True

    proj.close()
    assert proj.is_open is False
    assert scan.is_open is False


# ============================================================================
# 6. Pipeline Integration & Buffer Pool Stress Tests
# ============================================================================


def test_full_pipeline_execution(populated_table) -> None:
    """Verify end-to-end pipeline: Projection -> Filter -> TableScan."""
    tbl, _ = populated_table
    plan = Projection(
        Filter(
            TableScan(tbl),
            ComparisonPredicate("score", ">=", 80.0),
        ),
        ["name", "score"],
    )

    plan.open()
    rows = []
    while (r := plan.next()) is not None:
        rows.append((r["name"], r["score"]))
    plan.close()

    # Alice (95.5), Bob (80.0), Eve (90.0)
    assert rows == [("Alice", 95.5), ("Bob", 80.0), ("Eve", 90.0)]


def test_pipeline_under_pool_size_1(tmp_path: Path, sample_schema: Schema) -> None:
    """Verify pipeline functions correctly across multiple pages with pool_size = 1."""
    db_file = tmp_path / "tight_pool_exec.db"
    pf = PageFile(db_file)
    bpm = BufferPoolManager(pf, pool_size=1)
    hf = HeapFile(bpm)
    tbl = Table(10, "tight_table", sample_schema, hf)

    # Insert 150 rows spanning multiple pages
    for i in range(150):
        tbl.insert([i, f"user_{i:04d}", float(i), i % 2 == 0])

    assert tbl.heap_file.page_count > 1

    plan = Projection(
        Filter(TableScan(tbl), ComparisonPredicate("id", "<", 10)),
        ["id", "name"],
    )

    results = []
    with plan:
        while (row := plan.next()) is not None:
            results.append(row["id"])

    assert results == list(range(10))
    tbl.close()


def test_early_break_no_pin_leak(tmp_path: Path, sample_schema: Schema) -> None:
    """Verify early break from pipeline inside context manager leaves zero pinned frames."""
    db_file = tmp_path / "early_break.db"
    pf = PageFile(db_file)
    bpm = BufferPoolManager(pf, pool_size=3)
    hf = HeapFile(bpm)
    tbl = Table(11, "break_table", sample_schema, hf)

    for i in range(100):
        tbl.insert([i, f"user_{i}", float(i), True])

    plan = TableScan(tbl)
    with plan:
        for idx, row in enumerate(plan):
            if idx == 2:
                break  # Context manager guarantees plan.close() on exit

    assert plan.is_open is False
    # Ensure buffer pool has zero pinned frames
    for fid in range(bpm.pool_size):
        frame = bpm._frames[fid]
        assert frame.pin_count == 0

    tbl.close()


# ============================================================================
# 7. Error Propagation & Exception Preservation Tests
# ============================================================================


def test_open_failure_rollback(populated_table) -> None:
    """Verify open failure on leaf cascades clean rollback and preserves error."""
    tbl, _ = populated_table
    tbl.close()  # Force TableScan.open() to fail with StorageClosedError

    plan = Projection(Filter(TableScan(tbl), ComparisonPredicate("id", "=", 1)), ["id"])

    with pytest.raises(StorageClosedError):
        plan.open()

    assert plan.is_open is False
    assert plan.child.is_open is False
    assert plan.child.child.is_open is False


def test_next_failure_preserves_error_and_closes_operator(populated_table) -> None:
    """Verify unhandled error during next() preserves exception and transitions to CLOSED."""
    tbl, _ = populated_table
    plan = TableScan(tbl)
    plan.open()

    # Artificially close table mid-stream to trigger StorageClosedError
    tbl.close()

    with pytest.raises(StorageClosedError):
        plan.next()

    # Operator is closed
    assert plan.is_open is False

    # Subsequent next() raises OperatorClosedError
    with pytest.raises(OperatorClosedError):
        plan.next()


# ============================================================================
# 8. Context Manager and Python Iteration Tests
# ============================================================================


def test_standalone_for_loop_iteration(populated_table) -> None:
    """Verify bare for loop opens, streams, and closes automatically."""
    tbl, _ = populated_table
    plan = TableScan(tbl)

    names = [row["name"] for row in plan]
    assert len(names) == 5
    assert plan.is_open is False

    # Can be iterated again freshly
    names_again = [row["name"] for row in plan]
    assert names_again == names
    assert plan.is_open is False


def test_context_manager_with_for_loop_no_double_open(populated_table) -> None:
    """Verify 'with plan: for row in plan:' does not double-open or rewind."""
    tbl, _ = populated_table
    plan = TableScan(tbl)

    ids = []
    with plan:
        assert plan.is_open is True
        for row in plan:
            ids.append(row["id"])
        # Operator remains open until with-block exits
        assert plan.is_open is True

    assert plan.is_open is False
    assert ids == [1, 2, 3, 4, 5]


def test_context_manager_exception_teardown(populated_table) -> None:
    """Verify context manager guarantees close() even when consumer raises an exception."""
    tbl, _ = populated_table
    plan = TableScan(tbl)

    with pytest.raises(RuntimeError):
        with plan:
            assert plan.is_open is True
            raise RuntimeError("Consumer crash")

    assert plan.is_open is False


# ============================================================================
# 9. Additional Invariant & Edge Case Tests
# ============================================================================


def test_deep_pipeline_and_chained_filters(populated_table) -> None:
    """Verify deep pipeline chaining: Projection(Filter(Filter(TableScan)))."""
    tbl, _ = populated_table
    p1 = ComparisonPredicate("id", ">=", 2)
    p2 = ComparisonPredicate("active", "=", True)

    plan = Projection(
        Filter(
            Filter(
                TableScan(tbl),
                p1,
            ),
            p2,
        ),
        ["id", "name"],
    )

    with plan:
        rows = [r.values for r in plan]

    # Matching id >= 2 and active == True:
    # row 3 (Charlie, active=True) and row 5 (Eve, active=True)
    assert rows == [(3, "Charlie"), (5, "Eve")]


def test_predicate_immutability() -> None:
    """Verify Predicate instances cannot have attributes mutated."""
    p_comp = ComparisonPredicate("id", "=", 10)
    with pytest.raises(AttributeError):
        p_comp.column_name = "other"  # type: ignore[misc]

    p_null = IsNullPredicate("id")
    with pytest.raises(AttributeError):
        p_null.is_not_null = True  # type: ignore[misc]


def test_predicate_non_bool_raises_execution_error(populated_table) -> None:
    """Verify custom predicate returning a non-bool raises ExecutionError."""
    from strata_engine.execution.predicate import Predicate

    class BuggyPredicate(Predicate):
        def validate(self, schema: Schema) -> None:
            pass

        def evaluate(self, row: Tuple) -> bool:
            return "not a bool"  # type: ignore[return-value]

    tbl, _ = populated_table
    flt = Filter(TableScan(tbl), BuggyPredicate())

    flt.open()
    with pytest.raises(ExecutionError) as exc_info:
        flt.next()
    assert "returned non-bool" in str(exc_info.value)
    assert flt.is_open is False


def test_projection_reordered_fingerprint_distinct(populated_table) -> None:
    """Verify reordering projected columns produces a unique, distinct Schema fingerprint."""
    tbl, _ = populated_table
    scan = TableScan(tbl)
    p1 = Projection(scan, ["id", "name"])
    p2 = Projection(scan, ["name", "id"])

    assert p1.schema.column_names == ("id", "name")
    assert p2.schema.column_names == ("name", "id")
    assert p1.schema.fingerprint != p2.schema.fingerprint


def test_projection_more_than_256_columns_rejected(sample_schema) -> None:
    """Verify projection with > 256 columns is rejected."""
    # Build a schema with 256 columns
    cols = [Column(f"c_{i}", DataType.INTEGER) for i in range(256)]
    schema256 = Schema(cols)

    class DummyOperator(TableScan):
        @property
        def schema(self) -> Schema:
            return schema256

    dummy = DummyOperator.__new__(DummyOperator)
    dummy._table = None  # type: ignore[assignment]

    with pytest.raises(ValueError) as exc_info:
        Projection(dummy, [f"c_{i}" for i in range(256)] + ["extra"])
    assert "Projection must contain between 1 and 256 columns" in str(exc_info.value)


def test_bigint_comparison_predicate() -> None:
    """Verify BIGINT column comparison validation and evaluation."""
    schema = Schema([Column("big_id", DataType.BIGINT)])
    p = ComparisonPredicate("big_id", ">=", 100_000_000_000)
    p.validate(schema)

    row1 = Tuple([500_000_000_000], schema=schema)
    row2 = Tuple([10_000], schema=schema)

    assert p.evaluate(row1) is True
    assert p.evaluate(row2) is False

