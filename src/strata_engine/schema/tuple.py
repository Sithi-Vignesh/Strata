"""Immutable relational Tuple implementation for Strata."""

from typing import Any, Iterator, Optional, Sequence, Tuple as PyTuple, Union

from strata_engine.schema.exceptions import SchemaError, TupleArityError
from strata_engine.schema.schema import Schema


class Tuple:
    """Immutable relational tuple representing a typed row or generic value collection."""

    __slots__ = ("_values", "_schema")

    # Tuple is explicitly not hashable
    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        values: Sequence[Any],
        schema: Optional[Schema] = None,
    ) -> None:
        """Initialize an immutable Tuple.

        Args:
            values: Sequence of values.
            schema: Optional Schema defining the structure of this tuple.

        Raises:
            TupleArityError: If schema is provided and len(values) != len(schema).
            TypeError: If values is not a Sequence or schema is not a Schema/None.
        """
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise TypeError(f"Expected sequence of values, got {type(values).__name__}.")

        if schema is not None and not isinstance(schema, Schema):
            raise TypeError(f"Expected Schema instance or None, got {type(schema).__name__}.")

        val_tuple = tuple(values)

        if schema is not None:
            if len(val_tuple) != len(schema):
                raise TupleArityError(
                    f"Tuple arity mismatch: expected {len(schema)} values for schema, got {len(val_tuple)}."
                )

        self._values: PyTuple[Any, ...] = val_tuple
        self._schema: Optional[Schema] = schema

    @property
    def values(self) -> PyTuple[Any, ...]:
        """Return the immutable tuple of contained values."""
        return self._values

    @property
    def schema(self) -> Optional[Schema]:
        """Return the Schema bound to this tuple, if any."""
        return self._schema

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, key: Union[int, str]) -> Any:
        if isinstance(key, int):
            return self._values[key]
        elif isinstance(key, str):
            if self._schema is None:
                raise SchemaError(
                    f"Cannot access column '{key}' by name on a schema-less Tuple. A Schema is required for named access."
                )
            idx = self._schema.column_index(key)
            return self._values[idx]
        else:
            raise TypeError(f"Tuple subscript must be int or str, got {type(key).__name__}.")

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __repr__(self) -> str:
        schema_info = f", schema=0x{self._schema.fingerprint:08X}" if self._schema is not None else ""
        return f"Tuple({self._values!r}{schema_info})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tuple):
            return False

        if self._schema is not None and other._schema is not None:
            return (
                self._schema.fingerprint == other._schema.fingerprint
                and self._values == other._values
            )

        if self._schema is None and other._schema is None:
            return self._values == other._values

        return False
