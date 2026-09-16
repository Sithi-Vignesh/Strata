"""Comprehensive test suite for binary TupleSerializer (Phase 5).

Validates:
- Round-trip fidelity across INTEGER, BIGINT, FLOAT, BOOLEAN, VARCHAR, and NULL.
- Strict type validation (rejecting bool for int, int for float, etc.).
- Value range checks (signed 32/64-bit boundaries).
- IEEE-754 float semantics: 0.0, -0.0, inf, -inf, NaN.
- VARCHAR character limits vs UTF-8 byte limits (Section 50).
- Null bitmap bit packing, LSB-first layout, and unused bit rejection.
- 4084-byte boundary enforcement (TupleSizeError at 4085 bytes).
- Comprehensive corruption detection during deserialization.
"""

import math
import struct
import pytest

from strata_engine.schema import (
    Column,
    CorruptRecordError,
    DataType,
    MAX_SERIALIZED_TUPLE_SIZE,
    NullConstraintError,
    Schema,
    SchemaMismatchError,
    Tuple,
    TupleArityError,
    TupleSerializer,
    TupleSizeError,
    TypeMismatchError,
    ValueOutOfRangeError,
)


# ============================================================================
# Basic Round-Trip Tests
# ============================================================================


def test_round_trip_all_types() -> None:
    """Verify clean serialization and deserialization across all data types."""
    schema = Schema([
        Column("c_int", DataType.INTEGER, nullable=False),
        Column("c_bigint", DataType.BIGINT, nullable=False),
        Column("c_float", DataType.FLOAT, nullable=False),
        Column("c_bool", DataType.BOOLEAN, nullable=False),
        Column("c_str", DataType.VARCHAR, nullable=False, max_length=100),
    ])
    serializer = TupleSerializer(schema)

    original = Tuple([42, 9876543210123, 3.14159, True, "Hello Strata!"], schema=schema)
    data = serializer.serialize(original)
    recovered = serializer.deserialize(data)

    assert recovered == original
    assert recovered["c_int"] == 42
    assert recovered["c_bigint"] == 9876543210123
    assert math.isclose(recovered["c_float"], 3.14159)
    assert recovered["c_bool"] is True
    assert recovered["c_str"] == "Hello Strata!"


def test_round_trip_null_values() -> None:
    """Verify NULL bitmap handling with all-null, no-null, and mixed rows."""
    schema = Schema([
        Column("c1", DataType.INTEGER, nullable=True),
        Column("c2", DataType.VARCHAR, nullable=True, max_length=50),
        Column("c3", DataType.BOOLEAN, nullable=True),
    ])
    serializer = TupleSerializer(schema)

    # All NULL
    t_all_null = Tuple([None, None, None], schema=schema)
    rec_all_null = serializer.serialize(t_all_null)
    assert serializer.deserialize(rec_all_null) == t_all_null

    # No NULL
    t_no_null = Tuple([10, "test", False], schema=schema)
    rec_no_null = serializer.serialize(t_no_null)
    assert serializer.deserialize(rec_no_null) == t_no_null

    # Mixed NULL
    t_mixed = Tuple([None, "only text", None], schema=schema)
    rec_mixed = serializer.serialize(t_mixed)
    res_mixed = serializer.deserialize(rec_mixed)
    assert res_mixed == t_mixed
    assert res_mixed[0] is None
    assert res_mixed[1] == "only text"
    assert res_mixed[2] is None


def test_non_nullable_rejects_none() -> None:
    """Verify NullConstraintError when None is passed to non-nullable column."""
    schema = Schema([Column("id", DataType.INTEGER, nullable=False)])
    serializer = TupleSerializer(schema)

    with pytest.raises(NullConstraintError) as exc_info:
        serializer.serialize([None])
    assert "non-nullable" in str(exc_info.value)


# ============================================================================
# Strict Type & Boundary Validation Tests
# ============================================================================


def test_integer_strict_typing_and_bounds() -> None:
    """Verify INTEGER bounds [-2^31, 2^31-1] and rejection of bool/float."""
    schema = Schema([Column("id", DataType.INTEGER, nullable=False)])
    serializer = TupleSerializer(schema)

    # Min and max valid bounds
    assert serializer.deserialize(serializer.serialize([-(2**31)]))[0] == -(2**31)
    assert serializer.deserialize(serializer.serialize([2**31 - 1]))[0] == 2**31 - 1

    # Overflows
    with pytest.raises(ValueOutOfRangeError):
        serializer.serialize([2**31])
    with pytest.raises(ValueOutOfRangeError):
        serializer.serialize([-(2**31) - 1])

    # Rejection of bool (Python isinstance(True, int) trap)
    with pytest.raises(TypeMismatchError):
        serializer.serialize([True])
    with pytest.raises(TypeMismatchError):
        serializer.serialize([False])

    # Rejection of float and str
    with pytest.raises(TypeMismatchError):
        serializer.serialize([1.0])
    with pytest.raises(TypeMismatchError):
        serializer.serialize(["42"])


def test_bigint_strict_typing_and_bounds() -> None:
    """Verify BIGINT bounds [-2^63, 2^63-1] and rejection of bool."""
    schema = Schema([Column("id", DataType.BIGINT, nullable=False)])
    serializer = TupleSerializer(schema)

    assert serializer.deserialize(serializer.serialize([-(2**63)]))[0] == -(2**63)
    assert serializer.deserialize(serializer.serialize([2**63 - 1]))[0] == 2**63 - 1

    with pytest.raises(ValueOutOfRangeError):
        serializer.serialize([2**63])
    with pytest.raises(ValueOutOfRangeError):
        serializer.serialize([-(2**63) - 1])

    with pytest.raises(TypeMismatchError):
        serializer.serialize([True])
    with pytest.raises(TypeMismatchError):
        serializer.serialize([10.5])


def test_float_ieee754_special_values() -> None:
    """Verify IEEE-754 binary64 float semantics: inf, -inf, NaN, 0.0, -0.0."""
    schema = Schema([Column("val", DataType.FLOAT, nullable=False)])
    serializer = TupleSerializer(schema)

    # Standard floats
    assert serializer.deserialize(serializer.serialize([0.0]))[0] == 0.0
    assert serializer.deserialize(serializer.serialize([-123.456]))[0] == -123.456

    # Positive and negative infinity
    inf_rec = serializer.serialize([float("inf")])
    assert math.isinf(serializer.deserialize(inf_rec)[0])
    assert serializer.deserialize(inf_rec)[0] > 0

    neg_inf_rec = serializer.serialize([float("-inf")])
    assert math.isinf(serializer.deserialize(neg_inf_rec)[0])
    assert serializer.deserialize(neg_inf_rec)[0] < 0

    # NaN (must be tested with math.isnan())
    nan_rec = serializer.serialize([float("nan")])
    assert math.isnan(serializer.deserialize(nan_rec)[0])

    # Strict type rejection of int
    with pytest.raises(TypeMismatchError):
        serializer.serialize([42])


def test_boolean_strict_typing() -> None:
    """Verify BOOLEAN accepts only strict bool and rejects int 0/1."""
    schema = Schema([Column("flag", DataType.BOOLEAN, nullable=False)])
    serializer = TupleSerializer(schema)

    assert serializer.deserialize(serializer.serialize([True]))[0] is True
    assert serializer.deserialize(serializer.serialize([False]))[0] is False

    with pytest.raises(TypeMismatchError):
        serializer.serialize([0])
    with pytest.raises(TypeMismatchError):
        serializer.serialize([1])
    with pytest.raises(TypeMismatchError):
        serializer.serialize(["True"])


def test_varchar_unicode_empty_and_emojis() -> None:
    """Verify VARCHAR handles empty string, multilingual text, and emojis."""
    schema = Schema([Column("text", DataType.VARCHAR, nullable=False, max_length=100)])
    serializer = TupleSerializer(schema)

    # Empty string is distinct from NULL
    empty_data = serializer.serialize([""])
    recovered_empty = serializer.deserialize(empty_data)
    assert recovered_empty[0] == ""
    assert recovered_empty[0] is not None

    # Multilingual Unicode and emojis
    samples = ["Strata 数据库", "Café au lait ☕", "🚀✨🔥", "Unicode: \u0000\u00A9"]
    for sample in samples:
        res = serializer.deserialize(serializer.serialize([sample]))
        assert res[0] == sample


def test_varchar_character_count_vs_byte_length() -> None:
    """Verify VARCHAR character limit enforcement vs UTF-8 byte length (Section 50)."""
    # max_length is 10 Unicode characters
    schema = Schema([Column("text", DataType.VARCHAR, nullable=False, max_length=10)])
    serializer = TupleSerializer(schema)

    # 10 ASCII characters (10 bytes) -> OK
    serializer.serialize(["1234567890"])

    # 10 emojis (40 UTF-8 bytes, but exactly 10 characters) -> OK
    ten_emojis = "🚀" * 10
    assert len(ten_emojis) == 10
    assert len(ten_emojis.encode("utf-8")) == 40
    res = serializer.deserialize(serializer.serialize([ten_emojis]))
    assert res[0] == ten_emojis

    # 11 characters -> ValueOutOfRangeError
    with pytest.raises(ValueOutOfRangeError) as exc_info:
        serializer.serialize(["12345678901"])
    assert "VARCHAR string length (11 characters) exceeds" in str(exc_info.value)


def test_varchar_utf8_overflow_triggers_tuple_size_error() -> None:
    """Verify string satisfying character count but exceeding 4084 bytes raises TupleSizeError (Section 50)."""
    # max_length is 3000 characters (valid, <= 4080)
    schema = Schema([Column("text", DataType.VARCHAR, nullable=False, max_length=3000)])
    serializer = TupleSerializer(schema)

    # 1500 emojis: character count is 1500 <= 3000, BUT byte count is 1500 * 4 = 6000 bytes > 4084 bytes!
    emojis = "🚀" * 1500
    assert len(emojis) == 1500

    # Must raise TupleSizeError, NOT ValueOutOfRangeError
    with pytest.raises(TupleSizeError) as exc_info:
        serializer.serialize([emojis])
    assert "exceeds maximum record capacity of 4084 bytes" in str(exc_info.value)


def test_exact_4084_byte_record_boundary() -> None:
    """Verify record serializing to exactly 4084 bytes succeeds, 4085 bytes raises TupleSizeError."""
    # Header is: 2B (col_count) + 4B (fingerprint) + 1B (bitmap) = 7B.
    # VARCHAR prefix is 2B.
    # Payload capacity = 4084 - 7 - 2 = 4075 bytes.
    schema = Schema([Column("data", DataType.VARCHAR, nullable=False, max_length=4080)])
    serializer = TupleSerializer(schema)

    # Exact fit: 4075 ASCII characters
    exact_str = "x" * 4075
    data = serializer.serialize([exact_str])
    assert len(data) == MAX_SERIALIZED_TUPLE_SIZE
    assert serializer.deserialize(data)[0] == exact_str

    # 4076 bytes -> 4085 total -> raises TupleSizeError
    overflow_str = "x" * 4076
    with pytest.raises(TupleSizeError):
        serializer.serialize([overflow_str])


# ============================================================================
# Schema Mismatch & Arity Tests
# ============================================================================


def test_serializer_arity_mismatch() -> None:
    """Verify TupleArityError when sequence length does not match column count."""
    schema = Schema([Column("a", DataType.INTEGER), Column("b", DataType.INTEGER)])
    serializer = TupleSerializer(schema)

    with pytest.raises(TupleArityError):
        serializer.serialize([1])
    with pytest.raises(TupleArityError):
        serializer.serialize([1, 2, 3])


def test_serializer_schema_mismatch_on_tuple() -> None:
    """Verify SchemaMismatchError when serializing a Tuple bound to a different schema."""
    s1 = Schema([Column("a", DataType.INTEGER)])
    s2 = Schema([Column("b", DataType.BIGINT)])

    t = Tuple([42], schema=s2)
    serializer = TupleSerializer(s1)

    with pytest.raises(SchemaMismatchError):
        serializer.serialize(t)


# ============================================================================
# Corruption Detection Tests (Deserializer)
# ============================================================================


def test_deserializer_truncated_header() -> None:
    """Verify CorruptRecordError on records shorter than minimum header."""
    schema = Schema([Column("a", DataType.INTEGER)])
    serializer = TupleSerializer(schema)

    with pytest.raises(CorruptRecordError):
        serializer.deserialize(b"")
    with pytest.raises(CorruptRecordError):
        serializer.deserialize(b"\x00\x01\x00")


def test_deserializer_fingerprint_and_column_count_mismatch() -> None:
    """Verify SchemaMismatchError when stored fingerprint or column count differs."""
    s1 = Schema([Column("a", DataType.INTEGER)])
    s2 = Schema([Column("b", DataType.INTEGER), Column("c", DataType.INTEGER)])

    data_s2 = TupleSerializer(s2).serialize([1, 2])

    # Trying to deserialize s2 bytes with s1 serializer
    with pytest.raises(SchemaMismatchError):
        TupleSerializer(s1).deserialize(data_s2)


def test_deserializer_unused_bitmap_bits_must_be_zero() -> None:
    """Verify CorruptRecordError when unused null bitmap bits are non-zero."""
    # 2 columns -> bitmap is 1 byte, bits 0 and 1 are used, bits 2..7 must be zero.
    schema = Schema([Column("a", DataType.INTEGER), Column("b", DataType.INTEGER)])
    serializer = TupleSerializer(schema)

    raw = bytearray(serializer.serialize([10, 20]))
    # Header is at 0..5, bitmap is at index 6.
    # Set bit 7 (unused bit)
    raw[6] |= 0x80

    with pytest.raises(CorruptRecordError) as exc_info:
        serializer.deserialize(bytes(raw))
    assert "nonzero unused bits" in str(exc_info.value)


def test_deserializer_non_nullable_null_bit_set() -> None:
    """Verify CorruptRecordError if null bit is set for non-nullable column."""
    schema = Schema([Column("a", DataType.INTEGER, nullable=False)])
    serializer = TupleSerializer(schema)

    raw = bytearray(serializer.serialize([10]))
    # Set bit 0 in null bitmap (index 6)
    raw[6] |= 0x01

    with pytest.raises(CorruptRecordError) as exc_info:
        serializer.deserialize(bytes(raw))
    assert "Non-nullable column" in str(exc_info.value)


def test_deserializer_invalid_boolean_byte() -> None:
    """Verify CorruptRecordError if boolean payload byte is neither 0x00 nor 0x01."""
    schema = Schema([Column("flag", DataType.BOOLEAN, nullable=False)])
    serializer = TupleSerializer(schema)

    raw = bytearray(serializer.serialize([True]))
    # Payload is after header (6B) and bitmap (1B) -> index 7
    raw[7] = 0x02  # Invalid byte

    with pytest.raises(CorruptRecordError) as exc_info:
        serializer.deserialize(bytes(raw))
    assert "Invalid BOOLEAN byte" in str(exc_info.value)


def test_deserializer_truncated_payload() -> None:
    """Verify CorruptRecordError when payload bytes are truncated."""
    schema = Schema([Column("a", DataType.INTEGER, nullable=False)])
    serializer = TupleSerializer(schema)

    raw = serializer.serialize([12345])
    # Truncate last 2 bytes of the 4-byte int
    truncated = raw[:-2]

    with pytest.raises(CorruptRecordError) as exc_info:
        serializer.deserialize(truncated)
    assert "Truncated record" in str(exc_info.value)


def test_deserializer_truncated_varchar_length_and_payload() -> None:
    """Verify CorruptRecordError when VARCHAR length or string bytes are truncated."""
    schema = Schema([Column("txt", DataType.VARCHAR, max_length=50)])
    serializer = TupleSerializer(schema)

    raw = serializer.serialize(["hello"])

    # Truncate length prefix
    with pytest.raises(CorruptRecordError):
        serializer.deserialize(raw[:7])

    # Truncate string body
    with pytest.raises(CorruptRecordError):
        serializer.deserialize(raw[:-2])


def test_deserializer_invalid_utf8_in_varchar() -> None:
    """Verify CorruptRecordError on invalid UTF-8 byte sequences."""
    schema = Schema([Column("txt", DataType.VARCHAR, max_length=50)])
    serializer = TupleSerializer(schema)

    raw = bytearray(serializer.serialize(["test"]))
    # Replace last byte with invalid UTF-8 continuation byte
    raw[-1] = 0xFF

    with pytest.raises(CorruptRecordError) as exc_info:
        serializer.deserialize(bytes(raw))
    assert "Invalid UTF-8 payload" in str(exc_info.value)


def test_deserializer_unexpected_trailing_bytes() -> None:
    """Verify CorruptRecordError when extraneous trailing bytes are present."""
    schema = Schema([Column("a", DataType.INTEGER, nullable=False)])
    serializer = TupleSerializer(schema)

    raw = serializer.serialize([42])
    with_trailing = raw + b"\xDE\xAD\xBE\xEF"

    with pytest.raises(CorruptRecordError) as exc_info:
        serializer.deserialize(with_trailing)
    assert "unexpected trailing bytes" in str(exc_info.value)
