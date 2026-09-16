"""Strata Schema and Tuple subsystem.

Provides DataType, Column, Schema, Tuple, and TupleSerializer for relational
typing, schema validation, and binary record serialization.
"""

from strata_engine.schema.column import Column
from strata_engine.schema.data_type import DataType
from strata_engine.schema.exceptions import (
    ColumnNotFoundError,
    CorruptRecordError,
    DuplicateColumnError,
    InvalidColumnError,
    InvalidSchemaError,
    InvalidTypeError,
    NullConstraintError,
    SchemaError,
    SchemaMismatchError,
    SerializationError,
    TupleArityError,
    TupleSizeError,
    TypeMismatchError,
    ValueOutOfRangeError,
)
from strata_engine.schema.schema import Schema
from strata_engine.schema.serializer import MAX_SERIALIZED_TUPLE_SIZE, TupleSerializer
from strata_engine.schema.tuple import Tuple

__all__ = [
    "DataType",
    "Column",
    "Schema",
    "Tuple",
    "TupleSerializer",
    "MAX_SERIALIZED_TUPLE_SIZE",
    "SchemaError",
    "InvalidColumnError",
    "DuplicateColumnError",
    "InvalidSchemaError",
    "ColumnNotFoundError",
    "InvalidTypeError",
    "SerializationError",
    "TupleArityError",
    "TupleSizeError",
    "TypeMismatchError",
    "ValueOutOfRangeError",
    "NullConstraintError",
    "CorruptRecordError",
    "SchemaMismatchError",
]
