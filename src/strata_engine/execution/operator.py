"""Abstract base class for all Volcano-style relational execution operators."""

from abc import ABC, abstractmethod
from typing import Any, Iterator, Optional

from strata_engine.schema.schema import Schema
from strata_engine.schema.tuple import Tuple


class Operator(ABC):
    """Abstract base class defining the Volcano iterator model for execution operators.

    Operators support:
    - Explicit lifecycle: open(), next() -> Optional[Tuple], close()
    - Schema exposure: operator.schema
    - Open state check: operator.is_open
    - Context manager protocol: with operator: ...
    - Ownership-aware iteration: for row in operator: ...
    """

    @property
    @abstractmethod
    def schema(self) -> Schema:
        """Return the immutable Schema of tuples produced by this operator."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Return True if this operator is open and ready to produce tuples."""

    @abstractmethod
    def open(self) -> None:
        """Open or rewind this operator and prepare it to stream tuples from the beginning.

        If already open or exhausted, restarts iteration from the start.
        """

    @abstractmethod
    def next(self) -> Optional[Tuple]:
        """Fetch the next schema-bound Tuple, or return None if stream is exhausted.

        Raises:
            OperatorClosedError: If called on an uninitialized or closed operator.
        """

    @abstractmethod
    def close(self) -> None:
        """Close this operator and cascade closure to all owned child operators.

        Idempotent; safe to call repeatedly in any state. Must be exception-safe.
        """

    def __enter__(self) -> "Operator":
        """Context-manager entry: opens operator and returns self."""
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context-manager exit: deterministically closes operator."""
        self.close()

    def __iter__(self) -> Iterator[Tuple]:
        """Ownership-aware iteration convenience.

        If operator is not already open, opens it and guarantees closure upon exit
        or exhaustion. If already open (e.g. inside a 'with' block), does not reopen
        or prematurely close.
        """
        was_open = self.is_open
        if not was_open:
            self.open()
        try:
            while (row := self.next()) is not None:
                yield row
        finally:
            if not was_open:
                self.close()
