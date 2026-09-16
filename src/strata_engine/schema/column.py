"""Immutable Column specification for Strata schemas."""

import re
from typing import Optional

from strata_engine.schema.data_type import DataType
from strata_engine.schema.exceptions import InvalidColumnError, InvalidTypeError

COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_VARCHAR_LENGTH = 4080


class Column:
    """Immutable definition of a relational table column."""

    __slots__ = ("_name", "_data_type", "_nullable", "_max_length")

    def __init__(
        self,
        name: str,
        data_type: DataType,
        nullable: bool = False,
        max_length: Optional[int] = None,
    ) -> None:
        """Initialize a Column with validation.

        Args:
            name: Column identifier (1-64 ASCII characters matching ^[A-Za-z_][A-Za-z0-9_]{0,63}$).
            data_type: Instance of DataType enum.
            nullable: Exactly bool indicating whether NULL values are allowed.
            max_length: Maximum Unicode character count for VARCHAR (1 <= max_length <= 4080).
                Must be None for all fixed-width types.

        Raises:
            InvalidColumnError: If name, nullable, or max_length violates constraints.
            InvalidTypeError: If data_type is not an instance of DataType.
        """
        if not isinstance(name, str) or not COLUMN_NAME_PATTERN.match(name):
            raise InvalidColumnError(
                f"Invalid column name '{name}'. Column names must match '^[A-Za-z_][A-Za-z0-9_]{{0,63}}$'."
            )

        if not isinstance(data_type, DataType):
            raise InvalidTypeError(
                f"Expected DataType enum, got {type(data_type).__name__}."
            )

        if type(nullable) is not bool:
            raise InvalidColumnError(
                f"nullable must be a strict bool, got {type(nullable).__name__}."
            )

        if data_type == DataType.VARCHAR:
            if type(max_length) is not int or not (1 <= max_length <= MAX_VARCHAR_LENGTH):
                raise InvalidColumnError(
                    f"VARCHAR requires an integer max_length between 1 and {MAX_VARCHAR_LENGTH}, got {max_length}."
                )
        else:
            if max_length is not None:
                raise InvalidColumnError(
                    f"max_length is only valid for VARCHAR, but specified for {data_type.value}."
                )

        self._name: str = name
        self._data_type: DataType = data_type
        self._nullable: bool = nullable
        self._max_length: Optional[int] = max_length

    @property
    def name(self) -> str:
        """Return the column name with original casing preserved."""
        return self._name

    @property
    def data_type(self) -> DataType:
        """Return the DataType of the column."""
        return self._data_type

    @property
    def nullable(self) -> bool:
        """Return whether the column accepts NULL values."""
        return self._nullable

    @property
    def max_length(self) -> Optional[int]:
        """Return the maximum character length for VARCHAR, or None for fixed-width types."""
        return self._max_length

    def __repr__(self) -> str:
        null_str = "NULL" if self._nullable else "NOT NULL"
        len_str = f"({self._max_length})" if self._max_length is not None else ""
        return f"Column('{self._name}', {self._data_type.value}{len_str}, {null_str})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Column):
            return False
        return (
            self._name == other._name
            and self._data_type == other._data_type
            and self._nullable == other._nullable
            and self._max_length == other._max_length
        )
