"""RID-aware target selection for future table mutations."""

from strata_engine.catalog.table import Table
from strata_engine.execution.predicate import Predicate
from strata_engine.schema.tuple import Tuple
from strata_engine.storage.record_id import RecordId


class MutationTargetScan:
    """Materialize table rows selected for a future mutation.

    Unlike normal query operators, this selector preserves physical record
    identity.  It is intentionally table-scan-only and never mutates its
    borrowed table.
    """

    __slots__ = ("_table", "_predicate")

    def __init__(self, table: Table, predicate: Predicate | None = None) -> None:
        if not isinstance(table, Table):
            raise TypeError(f"Expected Table instance, got {type(table).__name__}.")
        if predicate is not None and not isinstance(predicate, Predicate):
            raise TypeError(
                "Expected Predicate instance or None for predicate, "
                f"got {type(predicate).__name__}."
            )

        if predicate is not None:
            predicate.validate(table.schema)

        self._table = table
        self._predicate = predicate

    @property
    def table(self) -> Table:
        """Return the borrowed source table."""
        return self._table

    @property
    def predicate(self) -> Predicate | None:
        """Return the optional predicate used during selection."""
        return self._predicate

    def collect(self) -> tuple[tuple[RecordId, Tuple], ...]:
        """Return a materialized snapshot of matching rows in table-scan order."""
        targets: list[tuple[RecordId, Tuple]] = []
        for record_id, row in self._table.scan():
            if self._predicate is None or self._predicate.evaluate(row):
                targets.append((record_id, row))
        return tuple(targets)
