"""Filter execution operator applying Predicates to child operator streams."""

from typing import Optional

from strata_engine.execution.exceptions import ExecutionError, OperatorClosedError
from strata_engine.execution.operator import Operator
from strata_engine.execution.predicate import Predicate
from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple


class Filter(Operator):
    """Execution operator that filters rows from a child operator using a Predicate.

    Preserves child schema and passes matching Tuple instances through without modification.
    """

    __slots__ = ("_child", "_predicate", "_is_open", "_exhausted")

    def __init__(self, child: Operator, predicate: Predicate) -> None:
        """Initialize Filter operator and validate predicate against child schema.

        Args:
            child: Source Operator producing tuples.
            predicate: Predicate instance to evaluate on each tuple.

        Raises:
            TypeError: If child is not an Operator or predicate is not a Predicate.
            ColumnNotFoundError: If predicate references a non-existent column.
            TypeMismatchError: If predicate literal type is incompatible with target column.
        """
        if not isinstance(child, Operator):
            raise TypeError(f"Expected Operator instance for child, got {type(child).__name__}.")
        if not isinstance(predicate, Predicate):
            raise TypeError(
                f"Expected Predicate instance for predicate, got {type(predicate).__name__}."
            )

        # Plan-time validation: Predicate validates against child schema
        predicate.validate(child.schema)

        self._child: Operator = child
        self._predicate: Predicate = predicate
        self._is_open: bool = False
        self._exhausted: bool = False

    @property
    def child(self) -> Operator:
        """Return the owned child operator."""
        return self._child

    @property
    def predicate(self) -> Predicate:
        """Return the filter predicate."""
        return self._predicate

    @property
    def schema(self) -> Schema:
        """Return the schema of tuples output by this filter (identical to child schema)."""
        return self._child.schema

    @property
    def is_open(self) -> bool:
        """Return True if this operator is open."""
        return self._is_open

    def open(self) -> None:
        """Open or rewind this filter and its child operator."""
        try:
            self._child.open()
            self._is_open = True
            self._exhausted = False
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def next(self) -> Optional[Tuple]:
        """Fetch the next Tuple satisfying the predicate, or return None if stream exhausted.

        Raises:
            OperatorClosedError: If filter is not currently open.
            ExecutionError: If predicate returns a non-bool result.
        """
        if not self.is_open:
            raise OperatorClosedError("Filter is not open. Call open() first.")

        if self._exhausted:
            return None

        try:
            while True:
                row = self._child.next()
                if row is None:
                    self._exhausted = True
                    return None

                matched = self._predicate.evaluate(row)
                if type(matched) is not bool:
                    raise ExecutionError(
                        f"Predicate {self._predicate!r} returned non-bool {type(matched).__name__}."
                    )
                if matched:
                    return row
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    def close(self) -> None:
        """Close this filter and cascade closure to the child operator.

        Idempotent and exception-safe.
        """
        self._is_open = False
        self._exhausted = False
        try:
            self._child.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        return f"Filter(child={self._child!r}, predicate={self._predicate!r}, status='{status}')"
