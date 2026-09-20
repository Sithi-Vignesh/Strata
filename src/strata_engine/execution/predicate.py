"""Relational filter predicate abstractions and implementations."""

from abc import ABC, abstractmethod
from typing import Any

from strata_engine.schema.data_type import DataType
from strata_engine.schema.exceptions import TypeMismatchError
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple

SUPPORTED_COMPARISON_OPS = ("=", "!=", "<>", "<", "<=", ">", ">=")


class Predicate(ABC):
    """Abstract immutable filter predicate operating on relational Tuples."""

    @abstractmethod
    def validate(self, schema: Schema) -> None:
        """Validate target columns and literal compatibility against schema.

        Args:
            schema: The input Schema of tuples to be evaluated.

        Raises:
            ColumnNotFoundError: If a referenced column does not exist in schema.
            TypeMismatchError: If a literal value is incompatible with the column's DataType.
            ValueError: If predicate configuration or operator is invalid.
        """

    @abstractmethod
    def evaluate(self, row: Tuple) -> bool:
        """Evaluate predicate against a schema-bound Tuple.

        Args:
            row: The Tuple to evaluate.

        Returns:
            Strict Python bool (True if row matches, False otherwise).
        """


class ComparisonPredicate(Predicate):
    """Evaluates a column comparison against a scalar literal (=, !=, <, <=, >, >=)."""

    __slots__ = ("_column_name", "_op", "_literal")

    def __init__(self, column_name: str, op: str, literal: Any) -> None:
        """Initialize a ComparisonPredicate.

        Args:
            column_name: Name of the column to compare.
            op: Comparison operator string (=, ==, !=, <>, <, <=, >, >=).
            literal: Scalar literal value to compare against. Cannot be None.

        Raises:
            ValueError: If literal is None or operator is unsupported.
            TypeError: If column_name or op is not a string.
        """
        if not isinstance(column_name, str):
            raise TypeError(f"column_name must be a str, got {type(column_name).__name__}.")
        if not isinstance(op, str):
            raise TypeError(f"op must be a str, got {type(op).__name__}.")
        if literal is None:
            raise ValueError(
                "ComparisonPredicate literal cannot be None. Use IsNullPredicate instead."
            )

        normalized_op = "=" if op == "==" else op
        if normalized_op not in SUPPORTED_COMPARISON_OPS:
            raise ValueError(f"Unsupported comparison operator '{op}'.")

        self._column_name: str = column_name
        self._op: str = normalized_op
        self._literal: Any = literal

    @property
    def column_name(self) -> str:
        """Return the target column name."""
        return self._column_name

    @property
    def op(self) -> str:
        """Return the normalized comparison operator."""
        return self._op

    @property
    def literal(self) -> Any:
        """Return the literal comparison value."""
        return self._literal

    def validate(self, schema: Schema) -> None:
        """Validate target column existence and literal type compatibility against schema."""
        col = schema.get_column_by_name(self._column_name)
        dt = col.data_type
        lit = self._literal

        if dt in (DataType.INTEGER, DataType.BIGINT):
            if type(lit) is not int or isinstance(lit, bool):
                raise TypeMismatchError(
                    f"Column '{col.name}' ({dt.value}) expects integer literal, got {type(lit).__name__}."
                )
        elif dt == DataType.FLOAT:
            if type(lit) not in (int, float) or isinstance(lit, bool):
                raise TypeMismatchError(
                    f"Column '{col.name}' (FLOAT) expects numeric literal, got {type(lit).__name__}."
                )
        elif dt == DataType.BOOLEAN:
            if type(lit) is not bool:
                raise TypeMismatchError(
                    f"Column '{col.name}' (BOOLEAN) expects bool literal, got {type(lit).__name__}."
                )
        elif dt == DataType.VARCHAR:
            if type(lit) is not str:
                raise TypeMismatchError(
                    f"Column '{col.name}' (VARCHAR) expects str literal, got {type(lit).__name__}."
                )

    def evaluate(self, row: Tuple) -> bool:
        """Evaluate comparison against row value.

        If row value is None, returns False for all comparison operators.
        Safely returns False on unexpected comparison TypeError.
        """
        val = row[self._column_name]
        if val is None:
            return False

        try:
            if self._op == "=":
                res = val == self._literal
            elif self._op in ("!=", "<>"):
                res = val != self._literal
            elif self._op == "<":
                res = val < self._literal
            elif self._op == "<=":
                res = val <= self._literal
            elif self._op == ">":
                res = val > self._literal
            elif self._op == ">=":
                res = val >= self._literal
            else:
                return False
            return bool(res)
        except TypeError:
            return False

    def __repr__(self) -> str:
        return f"ComparisonPredicate(column='{self._column_name}', op='{self._op}', literal={self._literal!r})"


class IsNullPredicate(Predicate):
    """Evaluates whether a column value IS NULL or IS NOT NULL."""

    __slots__ = ("_column_name", "_is_not_null")

    def __init__(self, column_name: str, is_not_null: bool = False) -> None:
        """Initialize an IsNullPredicate.

        Args:
            column_name: Name of the column to inspect.
            is_not_null: If True, evaluates IS NOT NULL. If False, evaluates IS NULL.

        Raises:
            TypeError: If column_name is not a string.
        """
        if not isinstance(column_name, str):
            raise TypeError(f"column_name must be a str, got {type(column_name).__name__}.")

        self._column_name: str = column_name
        self._is_not_null: bool = bool(is_not_null)

    @property
    def column_name(self) -> str:
        """Return the target column name."""
        return self._column_name

    @property
    def is_not_null(self) -> bool:
        """Return whether this predicate tests IS NOT NULL."""
        return self._is_not_null

    def validate(self, schema: Schema) -> None:
        """Validate that target column exists in schema."""
        schema.get_column_by_name(self._column_name)

    def evaluate(self, row: Tuple) -> bool:
        """Evaluate NULL check against row value."""
        val = row[self._column_name]
        is_null = val is None
        return bool(not is_null if self._is_not_null else is_null)

    def __repr__(self) -> str:
        kind = "IS NOT NULL" if self._is_not_null else "IS NULL"
        return f"IsNullPredicate(column='{self._column_name}', {kind})"
