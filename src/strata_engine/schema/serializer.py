"""Binary TupleSerializer for converting between Tuples and raw bytes."""

import struct
from typing import Any, Sequence, Union

from strata_engine.schema.data_type import DataType
from strata_engine.schema.exceptions import (
    CorruptRecordError,
    NullConstraintError,
    SchemaMismatchError,
    TupleArityError,
    TupleSizeError,
    TypeMismatchError,
    ValueOutOfRangeError,
)
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple

MAX_SERIALIZED_TUPLE_SIZE = 4084
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


class TupleSerializer:
    """Serializes and deserializes relational Tuples according to a fixed Schema."""

    __slots__ = ("_schema",)

    def __init__(self, schema: Schema) -> None:
        """Initialize TupleSerializer for the specified Schema.

        Args:
            schema: Schema instance.

        Raises:
            TypeError: If schema is not an instance of Schema.
        """
        if not isinstance(schema, Schema):
            raise TypeError(f"Expected Schema instance, got {type(schema).__name__}.")
        self._schema: Schema = schema

    @property
    def schema(self) -> Schema:
        """Return the schema associated with this serializer."""
        return self._schema

    def serialize(self, row: Union[Tuple, Sequence[Any]]) -> bytes:
        """Serialize a Tuple or Sequence of values into binary record format.

        Format:
            - column_count: 2 bytes unsigned big-endian (>H)
            - schema_fingerprint: 4 bytes unsigned big-endian (>I)
            - null_bitmap: ceil(column_count / 8) bytes (LSB-first)
            - payload: attribute values in ordinal order (0 bytes for NULLs)

        Args:
            row: Tuple instance or sequence of Python values.

        Returns:
            bytes: Encoded record bytes (length <= 4084).

        Raises:
            SchemaMismatchError: If row is a schema-bound Tuple with a different schema fingerprint.
            TupleArityError: If row value count does not match schema column count.
            TypeMismatchError: If any value does not match expected DataType.
            NullConstraintError: If None is supplied for a non-nullable column.
            ValueOutOfRangeError: If integer bounds or VARCHAR max_length is exceeded.
            TupleSizeError: If total serialized record exceeds 4084 bytes.
        """
        if isinstance(row, Tuple):
            if row.schema is not None and row.schema.fingerprint != self._schema.fingerprint:
                raise SchemaMismatchError(
                    f"Tuple schema fingerprint (0x{row.schema.fingerprint:08X}) "
                    f"does not match serializer schema fingerprint (0x{self._schema.fingerprint:08X})."
                )
            values = row.values
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            values = tuple(row)
        else:
            raise TypeError(f"Expected Tuple or Sequence of values, got {type(row).__name__}.")

        col_count = len(self._schema)
        if len(values) != col_count:
            raise TupleArityError(
                f"Expected {col_count} values for schema, got {len(values)}."
            )

        bitmap_len = (col_count + 7) // 8
        bitmap = bytearray(bitmap_len)
        payload = bytearray()

        for i, col in enumerate(self._schema.columns):
            val = values[i]

            if val is None:
                if not col.nullable:
                    raise NullConstraintError(
                        f"Column '{col.name}' is non-nullable but received None."
                    )
                bitmap[i // 8] |= 1 << (i % 8)
                continue

            dt = col.data_type
            if dt == DataType.INTEGER:
                if type(val) is not int:
                    raise TypeMismatchError(
                        f"Column '{col.name}' expects INTEGER (int), got {type(val).__name__}."
                    )
                if not (INT32_MIN <= val <= INT32_MAX):
                    raise ValueOutOfRangeError(
                        f"INTEGER value {val} out of 32-bit signed range [{INT32_MIN}, {INT32_MAX}]."
                    )
                payload.extend(struct.pack(">i", val))

            elif dt == DataType.BIGINT:
                if type(val) is not int:
                    raise TypeMismatchError(
                        f"Column '{col.name}' expects BIGINT (int), got {type(val).__name__}."
                    )
                if not (INT64_MIN <= val <= INT64_MAX):
                    raise ValueOutOfRangeError(
                        f"BIGINT value {val} out of 64-bit signed range [{INT64_MIN}, {INT64_MAX}]."
                    )
                payload.extend(struct.pack(">q", val))

            elif dt == DataType.FLOAT:
                if type(val) is not float:
                    raise TypeMismatchError(
                        f"Column '{col.name}' expects FLOAT (float), got {type(val).__name__}."
                    )
                payload.extend(struct.pack(">d", val))

            elif dt == DataType.BOOLEAN:
                if type(val) is not bool:
                    raise TypeMismatchError(
                        f"Column '{col.name}' expects BOOLEAN (bool), got {type(val).__name__}."
                    )
                payload.append(1 if val else 0)

            elif dt == DataType.VARCHAR:
                if type(val) is not str:
                    raise TypeMismatchError(
                        f"Column '{col.name}' expects VARCHAR (str), got {type(val).__name__}."
                    )
                assert col.max_length is not None
                if len(val) > col.max_length:
                    raise ValueOutOfRangeError(
                        f"VARCHAR string length ({len(val)} characters) exceeds column '{col.name}' limit of {col.max_length}."
                    )
                encoded = val.encode("utf-8")
                if len(encoded) > 65535:
                    raise TupleSizeError(
                        f"UTF-8 encoded string of {len(encoded)} bytes exceeds 2-byte prefix capacity (65535)."
                    )
                payload.extend(struct.pack(">H", len(encoded)))
                payload.extend(encoded)

        # Header: column_count (uint16) + fingerprint (uint32)
        header = struct.pack(">HI", col_count, self._schema.fingerprint)
        total_record = header + bytes(bitmap) + bytes(payload)

        if len(total_record) > MAX_SERIALIZED_TUPLE_SIZE:
            raise TupleSizeError(
                f"Serialized tuple size of {len(total_record)} bytes exceeds maximum record capacity of {MAX_SERIALIZED_TUPLE_SIZE} bytes."
            )

        return total_record

    def deserialize(self, data: Union[bytes, bytearray]) -> Tuple:
        """Deserialize raw binary record bytes into a schema-bound Tuple.

        Args:
            data: Binary record bytes or bytearray.

        Returns:
            Tuple instance bound to self.schema.

        Raises:
            CorruptRecordError: If binary layout, lengths, types, or boundaries are corrupted.
            SchemaMismatchError: If column count or schema fingerprint does not match.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"Expected bytes or bytearray, got {type(data).__name__}.")

        total_len = len(data)
        if total_len > MAX_SERIALIZED_TUPLE_SIZE:
            raise CorruptRecordError(
                f"Record length {total_len} exceeds maximum capacity of {MAX_SERIALIZED_TUPLE_SIZE} bytes."
            )

        col_count = len(self._schema)
        bitmap_len = (col_count + 7) // 8
        min_header_len = 6 + bitmap_len

        if total_len < min_header_len:
            raise CorruptRecordError(
                f"Record of {total_len} bytes is too short to contain header of {min_header_len} bytes."
            )

        stored_col_count, stored_fingerprint = struct.unpack(">HI", data[:6])

        if not (1 <= stored_col_count <= 256):
            raise CorruptRecordError(
                f"Invalid stored column count {stored_col_count}. Must be in [1, 256]."
            )

        if stored_col_count != col_count:
            raise SchemaMismatchError(
                f"Stored column count ({stored_col_count}) does not match schema column count ({col_count})."
            )

        if stored_fingerprint != self._schema.fingerprint:
            raise SchemaMismatchError(
                f"Stored schema fingerprint (0x{stored_fingerprint:08X}) does not match "
                f"expected schema fingerprint (0x{self._schema.fingerprint:08X})."
            )

        bitmap = data[6:min_header_len]

        # Verify unused bits in the last bitmap byte are zero
        extra_bits = (col_count % 8)
        if extra_bits != 0:
            unused_mask = ((1 << (8 - extra_bits)) - 1) << extra_bits
            if bitmap[-1] & unused_mask != 0:
                raise CorruptRecordError(
                    f"Null bitmap contains nonzero unused bits (byte: 0x{bitmap[-1]:02X}, mask: 0x{unused_mask:02X})."
                )

        cursor = min_header_len
        values: list[Any] = []

        for i, col in enumerate(self._schema.columns):
            is_null = (bitmap[i // 8] & (1 << (i % 8))) != 0
            if is_null:
                if not col.nullable:
                    raise CorruptRecordError(
                        f"Non-nullable column '{col.name}' has null bit set in bitmap."
                    )
                values.append(None)
                continue

            dt = col.data_type
            if dt == DataType.INTEGER:
                if cursor + 4 > total_len:
                    raise CorruptRecordError(
                        f"Truncated record: insufficient bytes for INTEGER column '{col.name}'."
                    )
                val = struct.unpack(">i", data[cursor : cursor + 4])[0]
                cursor += 4
                values.append(val)

            elif dt == DataType.BIGINT:
                if cursor + 8 > total_len:
                    raise CorruptRecordError(
                        f"Truncated record: insufficient bytes for BIGINT column '{col.name}'."
                    )
                val = struct.unpack(">q", data[cursor : cursor + 8])[0]
                cursor += 8
                values.append(val)

            elif dt == DataType.FLOAT:
                if cursor + 8 > total_len:
                    raise CorruptRecordError(
                        f"Truncated record: insufficient bytes for FLOAT column '{col.name}'."
                    )
                val = struct.unpack(">d", data[cursor : cursor + 8])[0]
                cursor += 8
                values.append(val)

            elif dt == DataType.BOOLEAN:
                if cursor + 1 > total_len:
                    raise CorruptRecordError(
                        f"Truncated record: insufficient bytes for BOOLEAN column '{col.name}'."
                    )
                b = data[cursor]
                cursor += 1
                if b not in (0, 1):
                    raise CorruptRecordError(
                        f"Invalid BOOLEAN byte value 0x{b:02X} (must be 0x00 or 0x01)."
                    )
                values.append(True if b == 1 else False)

            elif dt == DataType.VARCHAR:
                if cursor + 2 > total_len:
                    raise CorruptRecordError(
                        f"Truncated record: insufficient bytes for VARCHAR length prefix on '{col.name}'."
                    )
                str_len = struct.unpack(">H", data[cursor : cursor + 2])[0]
                cursor += 2
                if cursor + str_len > total_len:
                    raise CorruptRecordError(
                        f"Truncated record: VARCHAR column '{col.name}' expects {str_len} bytes, but only {total_len - cursor} remain."
                    )
                str_bytes = data[cursor : cursor + str_len]
                cursor += str_len
                try:
                    s = str_bytes.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise CorruptRecordError(
                        f"Invalid UTF-8 payload in VARCHAR column '{col.name}': {exc}."
                    ) from exc
                assert col.max_length is not None
                if len(s) > col.max_length:
                    raise CorruptRecordError(
                        f"VARCHAR character length {len(s)} exceeds column '{col.name}' limit of {col.max_length}."
                    )
                values.append(s)

        if cursor != total_len:
            raise CorruptRecordError(
                f"Record has {total_len - cursor} unexpected trailing bytes after decoding all columns."
            )

        return Tuple(values, schema=self._schema)
