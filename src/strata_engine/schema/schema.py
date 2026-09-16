"""Immutable Schema definition for Strata tables."""

from typing import Dict, Iterator, Optional, Sequence, Tuple as PyTuple, Union
import zlib

from strata_engine.schema.column import Column
from strata_engine.schema.exceptions import (
    ColumnNotFoundError,
    DuplicateColumnError,
    InvalidColumnError,
    InvalidSchemaError,
)

MIN_SCHEMA_COLUMNS = 1
MAX_SCHEMA_COLUMNS = 256


class Schema:
    """Immutable sequence of Column definitions representing a table's structure."""

    __slots__ = (
        "_columns",
        "_column_names",
        "_name_to_index",
        "_fingerprint",
    )

    def __init__(self, columns: Sequence[Column]) -> None:
        """Initialize an immutable Schema.

        Args:
            columns: Sequence of Column objects.

        Raises:
            InvalidSchemaError: If columns count is < 1 or > 256, or if an item is not a Column.
            DuplicateColumnError: If two columns share the same case-insensitive name.
        """
        if not isinstance(columns, Sequence):
            raise InvalidSchemaError(
                f"Expected sequence of Column objects, got {type(columns).__name__}."
            )

        col_count = len(columns)
        if not (MIN_SCHEMA_COLUMNS <= col_count <= MAX_SCHEMA_COLUMNS):
            raise InvalidSchemaError(
                f"Schema must contain between {MIN_SCHEMA_COLUMNS} and {MAX_SCHEMA_COLUMNS} columns, got {col_count}."
            )

        validated_columns: list[Column] = []
        name_to_index: Dict[str, int] = {}

        for i, col in enumerate(columns):
            if not isinstance(col, Column):
                raise InvalidSchemaError(
                    f"Column at index {i} is not a Column instance, got {type(col).__name__}."
                )

            lower_name = col.name.lower()
            if lower_name in name_to_index:
                first_idx = name_to_index[lower_name]
                first_name = validated_columns[first_idx].name
                raise DuplicateColumnError(
                    f"Duplicate column name '{col.name}' (matches existing column '{first_name}' case-insensitively)."
                )

            name_to_index[lower_name] = i
            validated_columns.append(col)

        self._columns: PyTuple[Column, ...] = tuple(validated_columns)
        self._column_names: PyTuple[str, ...] = tuple(c.name for c in self._columns)
        self._name_to_index: Dict[str, int] = name_to_index

        # Calculate deterministic 32-bit CRC32 schema fingerprint
        canonical_spec = "\n".join(
            f"{i}:{c.name.lower()}:{c.data_type.value}:"
            f"{'1' if c.nullable else '0'}:"
            f"{c.max_length if c.max_length is not None else '-'}"
            for i, c in enumerate(self._columns)
        )
        self._fingerprint: int = zlib.crc32(canonical_spec.encode("utf-8")) & 0xFFFFFFFF

    @property
    def columns(self) -> PyTuple[Column, ...]:
        """Return an immutable tuple of Column definitions in ordinal order."""
        return self._columns

    @property
    def column_names(self) -> PyTuple[str, ...]:
        """Return an immutable tuple of column names with original casing preserved."""
        return self._column_names

    @property
    def column_count(self) -> int:
        """Return the number of columns in the schema."""
        return len(self._columns)

    @property
    def fingerprint(self) -> int:
        """Return the deterministic 32-bit CRC32 schema fingerprint."""
        return self._fingerprint

    def column_index(self, name: str) -> int:
        """Return the ordinal index of a column by case-insensitive name.

        Args:
            name: Column name to look up.

        Returns:
            Ordinal integer index (0 <= index < len(schema)).

        Raises:
            ColumnNotFoundError: If the column name is not in the schema.
        """
        if not isinstance(name, str):
            raise ColumnNotFoundError(f"Column name must be a string, got {type(name).__name__}.")

        lower = name.lower()
        if lower not in self._name_to_index:
            raise ColumnNotFoundError(f"Column '{name}' not found in schema.")
        return self._name_to_index[lower]

    def has_column(self, name: str) -> bool:
        """Return whether a column exists by case-insensitive name."""
        if not isinstance(name, str):
            return False
        return name.lower() in self._name_to_index

    def get_column(self, index: int) -> Column:
        """Return the Column at ordinal index."""
        return self._columns[index]

    def get_column_by_name(self, name: str) -> Column:
        """Return the Column matching case-insensitive name."""
        idx = self.column_index(name)
        return self._columns[idx]

    def __len__(self) -> int:
        return len(self._columns)

    def __getitem__(self, key: Union[int, str]) -> Column:
        if isinstance(key, int):
            return self._columns[key]
        elif isinstance(key, str):
            return self.get_column_by_name(key)
        else:
            raise TypeError(f"Schema key must be int or str, got {type(key).__name__}.")

    def __iter__(self) -> Iterator[Column]:
        return iter(self._columns)

    def __repr__(self) -> str:
        cols_repr = ", ".join(repr(c) for c in self._columns)
        return f"Schema([{cols_repr}], fingerprint=0x{self._fingerprint:08X})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Schema):
            return False
        return self._columns == other._columns
