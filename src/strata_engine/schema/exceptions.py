"""Exceptions for Strata schema and tuple serialization subsystems."""

from strata_engine.exceptions import StrataError


class SchemaError(StrataError):
    """Base exception for all schema definition and inspection errors."""


class InvalidColumnError(SchemaError):
    """Raised when a column definition violates structural or naming rules."""


class DuplicateColumnError(SchemaError):
    """Raised when duplicate column names are detected in a schema."""


class InvalidSchemaError(SchemaError):
    """Raised when a schema violates general invariants (e.g. empty or > 256 columns)."""


class ColumnNotFoundError(SchemaError):
    """Raised when accessing a non-existent column name on a schema or tuple."""


class InvalidTypeError(SchemaError):
    """Raised when an invalid or unsupported data type is specified."""


class SerializationError(StrataError):
    """Base exception for all tuple serialization and deserialization errors."""


class TupleArityError(SerializationError):
    """Raised when a tuple does not match the expected number of schema columns."""


class TupleSizeError(SerializationError):
    """Raised when a serialized tuple exceeds the maximum allowable record capacity (4084 bytes)."""


class TypeMismatchError(SerializationError):
    """Raised when a runtime value does not match the column's expected DataType."""


class ValueOutOfRangeError(SerializationError):
    """Raised when a value exceeds the physical range or defined bounds for its type."""


class NullConstraintError(SerializationError):
    """Raised when None is provided for a non-nullable column."""


class CorruptRecordError(SerializationError):
    """Raised when deserializing a malformed, truncated, or corrupted binary record."""


class SchemaMismatchError(SerializationError):
    """Raised when a serialized record's schema fingerprint or column count does not match the expected schema."""
