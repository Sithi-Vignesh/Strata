"""Comprehensive unit tests for Strata Schema subsystem (Phase 5).

Tests:
- DataType enum completeness.
- Column construction, validation, identifier grammar, and immutability.
- Schema construction, column limits [1, 256], duplicate detection, lookups, and CRC32 fingerprinting.
- Tuple container, schema-bound vs schema-less behavior, strict equality, and unhashability.
"""

import pytest

from strata_engine.schema import (
    Column,
    ColumnNotFoundError,
    DataType,
    DuplicateColumnError,
    InvalidColumnError,
    InvalidSchemaError,
    InvalidTypeError,
    Schema,
    SchemaError,
    Tuple,
    TupleArityError,
)


# ============================================================================
# DataType Tests
# ============================================================================


def test_data_type_enum_members() -> None:
    """Verify exactly five data types exist in DataType."""
    expected = {"INTEGER", "BIGINT", "FLOAT", "BOOLEAN", "VARCHAR"}
    actual = {dt.value for dt in DataType}
    assert actual == expected
    assert len(DataType) == 5


# ============================================================================
# Column Tests
# ============================================================================


def test_column_valid_definitions() -> None:
    """Verify construction of valid columns across all types."""
    col_int = Column("id", DataType.INTEGER, nullable=False)
    assert col_int.name == "id"
    assert col_int.data_type == DataType.INTEGER
    assert col_int.nullable is False
    assert col_int.max_length is None

    col_str = Column("username", DataType.VARCHAR, nullable=True, max_length=64)
    assert col_str.name == "username"
    assert col_str.data_type == DataType.VARCHAR
    assert col_str.nullable is True
    assert col_str.max_length == 64


def test_column_name_grammar_boundaries() -> None:
    """Verify name identifier regex bounds (1-64 characters)."""
    # 1-char name
    c1 = Column("a", DataType.INTEGER)
    assert c1.name == "a"

    # 64-char name
    name_64 = "a" * 64
    c64 = Column(name_64, DataType.INTEGER)
    assert c64.name == name_64

    # 65-char name must fail
    name_65 = "a" * 65
    with pytest.raises(InvalidColumnError) as exc_info:
        Column(name_65, DataType.INTEGER)
    assert "Invalid column name" in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_name",
    [
        "",  # empty
        "1col",  # starts with digit
        "col name",  # contains space
        "col:name",  # contains colon
        "col\nname",  # contains newline
        "col\rname",  # contains carriage return
        "col-name",  # contains hyphen
        "col@name",  # contains symbol
        "café",  # non-ASCII unicode
    ],
)
def test_column_invalid_names(bad_name: str) -> None:
    """Verify illegal names raise InvalidColumnError."""
    with pytest.raises(InvalidColumnError):
        Column(bad_name, DataType.INTEGER)


def test_column_data_type_validation() -> None:
    """Verify non-DataType argument raises InvalidTypeError."""
    with pytest.raises(InvalidTypeError):
        Column("col", "INTEGER")  # type: ignore[arg-type]


def test_column_nullable_strict_bool() -> None:
    """Verify nullable rejects non-bool values."""
    with pytest.raises(InvalidColumnError):
        Column("col", DataType.INTEGER, nullable=1)  # type: ignore[arg-type]
    with pytest.raises(InvalidColumnError):
        Column("col", DataType.INTEGER, nullable="True")  # type: ignore[arg-type]


def test_column_varchar_max_length_rules() -> None:
    """Verify VARCHAR requires max_length in range [1, 4080]."""
    # Missing max_length
    with pytest.raises(InvalidColumnError):
        Column("name", DataType.VARCHAR)

    # Zero max_length
    with pytest.raises(InvalidColumnError):
        Column("name", DataType.VARCHAR, max_length=0)

    # Negative max_length
    with pytest.raises(InvalidColumnError):
        Column("name", DataType.VARCHAR, max_length=-1)

    # 4080 is valid
    col = Column("name", DataType.VARCHAR, max_length=4080)
    assert col.max_length == 4080

    # 4081 is invalid
    with pytest.raises(InvalidColumnError):
        Column("name", DataType.VARCHAR, max_length=4081)

    # Float max_length rejected
    with pytest.raises(InvalidColumnError):
        Column("name", DataType.VARCHAR, max_length=50.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("dt", [DataType.INTEGER, DataType.BIGINT, DataType.FLOAT, DataType.BOOLEAN])
def test_column_fixed_types_reject_max_length(dt: DataType) -> None:
    """Verify fixed-width types reject max_length."""
    with pytest.raises(InvalidColumnError):
        Column("col", dt, max_length=10)


def test_column_equality_and_repr() -> None:
    """Verify Column equality and string representation."""
    c1 = Column("id", DataType.INTEGER, nullable=False)
    c2 = Column("id", DataType.INTEGER, nullable=False)
    c3 = Column("id", DataType.INTEGER, nullable=True)

    assert c1 == c2
    assert c1 != c3
    assert c1 != "id"
    assert "NOT NULL" in repr(c1)
    assert "NULL" in repr(c3)


# ============================================================================
# Schema Tests
# ============================================================================


def test_schema_valid_construction() -> None:
    """Verify construction and properties of valid Schema."""
    cols = [
        Column("Id", DataType.INTEGER, nullable=False),
        Column("Username", DataType.VARCHAR, nullable=False, max_length=50),
        Column("Score", DataType.FLOAT, nullable=True),
    ]
    schema = Schema(cols)

    assert len(schema) == 3
    assert schema.column_count == 3
    assert schema.column_names == ("Id", "Username", "Score")
    assert schema[0] == cols[0]
    assert schema["Id"] == cols[0]
    assert schema["id"] == cols[0]  # Case-insensitive
    assert schema["USERNAME"] == cols[1]
    assert schema.column_index("score") == 2
    assert schema.has_column("username") is True
    assert schema.has_column("nonexistent") is False


def test_schema_column_boundaries() -> None:
    """Verify schema size limits [1, 256]."""
    # 0 columns
    with pytest.raises(InvalidSchemaError):
        Schema([])

    # 1 column
    s1 = Schema([Column("c", DataType.INTEGER)])
    assert len(s1) == 1

    # 256 columns
    s256 = Schema([Column(f"c_{i}", DataType.INTEGER) for i in range(256)])
    assert len(s256) == 256

    # 257 columns
    with pytest.raises(InvalidSchemaError):
        Schema([Column(f"c_{i}", DataType.INTEGER) for i in range(257)])


def test_schema_duplicate_column_names_rejected() -> None:
    """Verify duplicate column names are rejected case-insensitively."""
    # Exact duplicate
    with pytest.raises(DuplicateColumnError):
        Schema([Column("id", DataType.INTEGER), Column("id", DataType.INTEGER)])

    # Case-insensitive duplicate
    with pytest.raises(DuplicateColumnError) as exc_info:
        Schema([Column("UserId", DataType.INTEGER), Column("userid", DataType.INTEGER)])
    assert "UserId" in str(exc_info.value)
    assert "userid" in str(exc_info.value)


def test_schema_lookups_and_errors() -> None:
    """Verify lookup exceptions."""
    schema = Schema([Column("id", DataType.INTEGER)])

    with pytest.raises(ColumnNotFoundError):
        schema["missing"]

    with pytest.raises(ColumnNotFoundError):
        schema.column_index("missing")

    with pytest.raises(ColumnNotFoundError):
        schema.get_column_by_name("missing")

    with pytest.raises(TypeError):
        schema[1.5]  # type: ignore[index]


def test_schema_fingerprint_determinism_and_uniqueness() -> None:
    """Verify 32-bit CRC32 fingerprint behavior."""
    s1 = Schema([Column("Id", DataType.INTEGER, nullable=False), Column("Name", DataType.VARCHAR, max_length=50)])
    s2 = Schema([Column("id", DataType.INTEGER, nullable=False), Column("name", DataType.VARCHAR, max_length=50)])
    # Case-insensitive names yield the identical canonical fingerprint
    assert s1.fingerprint == s2.fingerprint
    assert isinstance(s1.fingerprint, int)
    assert 0 <= s1.fingerprint <= 0xFFFFFFFF

    # Changing type changes fingerprint
    s_diff_type = Schema([Column("Id", DataType.BIGINT, nullable=False), Column("Name", DataType.VARCHAR, max_length=50)])
    assert s1.fingerprint != s_diff_type.fingerprint

    # Changing nullability changes fingerprint
    s_diff_null = Schema([Column("Id", DataType.INTEGER, nullable=True), Column("Name", DataType.VARCHAR, max_length=50)])
    assert s1.fingerprint != s_diff_null.fingerprint

    # Changing max_length changes fingerprint
    s_diff_len = Schema([Column("Id", DataType.INTEGER, nullable=False), Column("Name", DataType.VARCHAR, max_length=60)])
    assert s1.fingerprint != s_diff_len.fingerprint

    # Changing ordinal position changes fingerprint
    s_reversed = Schema([Column("Name", DataType.VARCHAR, max_length=50), Column("Id", DataType.INTEGER, nullable=False)])
    assert s1.fingerprint != s_reversed.fingerprint


# ============================================================================
# Tuple Tests
# ============================================================================


def test_tuple_schema_less() -> None:
    """Verify schema-less Tuple acts as a generic immutable container."""
    t = Tuple([1, "Alice", True])
    assert len(t) == 3
    assert t[0] == 1
    assert t[1] == "Alice"
    assert t[2] is True
    assert t.values == (1, "Alice", True)
    assert t.schema is None

    # Access by name on schema-less Tuple raises SchemaError
    with pytest.raises(SchemaError):
        _ = t["name"]


def test_tuple_schema_bound() -> None:
    """Verify schema-bound Tuple supports named lookups and arity enforcement."""
    schema = Schema([
        Column("Id", DataType.INTEGER),
        Column("Name", DataType.VARCHAR, max_length=50),
    ])

    # Correct arity
    t = Tuple([101, "Bob"], schema=schema)
    assert t.schema is schema
    assert t[0] == 101
    assert t["Id"] == 101
    assert t["id"] == 101  # Case-insensitive
    assert t["name"] == "Bob"

    # Arity mismatch
    with pytest.raises(TupleArityError):
        Tuple([101], schema=schema)

    with pytest.raises(TupleArityError):
        Tuple([101, "Bob", 42], schema=schema)


def test_tuple_immutability() -> None:
    """Verify Tuple values cannot be modified externally."""
    vals = [1, 2, 3]
    t = Tuple(vals)
    vals[0] = 999
    assert t[0] == 1


def test_tuple_strict_equality() -> None:
    """Verify strict equality contract across schema-bound and schema-less tuples."""
    s1 = Schema([Column("a", DataType.INTEGER)])
    s2 = Schema([Column("a", DataType.INTEGER)])
    s3 = Schema([Column("b", DataType.BIGINT)])

    t_bound1 = Tuple([42], schema=s1)
    t_bound2 = Tuple([42], schema=s2)
    t_bound3 = Tuple([42], schema=s3)
    t_less1 = Tuple([42])
    t_less2 = Tuple([42])

    # Case 1: Bound + Bound with same fingerprint and values
    assert t_bound1 == t_bound2

    # Case 2: Bound + Bound with different schema
    assert t_bound1 != t_bound3

    # Case 3: Less + Less with same values
    assert t_less1 == t_less2

    # Case 4: Bound + Less NEVER equal
    assert t_bound1 != t_less1
    assert t_less1 != t_bound1

    # Case 5: Tuple + Python list/tuple NEVER equal
    assert t_bound1 != [42]
    assert t_bound1 != (42,)
    assert t_less1 != (42,)


def test_tuple_unhashable() -> None:
    """Verify Tuple is strictly unhashable (__hash__ is None)."""
    assert Tuple.__hash__ is None
    t = Tuple([1, 2])
    with pytest.raises(TypeError) as exc_info:
        hash(t)
    assert "unhashable type" in str(exc_info.value)
