"""Record identifier representation and validation.

RecordId uniquely identifies a record within the storage engine by combining
a PageId with a slot index within that page's slot directory.
"""

from typing import Any, Union
from strata_engine.storage.exceptions import InvalidSlotIdError
from strata_engine.storage.page_id import PageId, validate_page_id


class RecordId:
    """Strictly immutable, hashable identifier pointing to a record: (PageId, slot_id).

    Guarantees:
    - Instances are strictly read-only and immutable after construction.
    - Both page_id and slot_id are validated upon initialization.
    - Suitable as keys in hash tables, caches, and index entries.
    """

    __slots__ = ("_page_id", "_slot_id")

    def __init__(self, page_id: Union[PageId, int], slot_id: int) -> None:
        """Initialize and validate an immutable RecordId.

        Args:
            page_id: PageId or valid non-negative integer.
            slot_id: Non-negative integer representing the slot index.

        Raises:
            InvalidPageIdError: If page_id is invalid.
            InvalidSlotIdError: If slot_id is not an integer, is a bool, or is negative.
        """
        valid_pid = validate_page_id(page_id)

        if isinstance(slot_id, bool) or not isinstance(slot_id, int):
            raise InvalidSlotIdError(
                f"slot_id must be an integer, got {type(slot_id).__name__}: {slot_id!r}"
            )
        if slot_id < 0:
            raise InvalidSlotIdError(f"slot_id must be non-negative, got: {slot_id}")

        object.__setattr__(self, "_page_id", valid_pid)
        object.__setattr__(self, "_slot_id", slot_id)

    @property
    def page_id(self) -> PageId:
        """Return the PageId component."""
        return self._page_id

    @property
    def slot_id(self) -> int:
        """Return the slot index component."""
        return self._slot_id

    def __setattr__(self, name: str, value: Any) -> None:
        """Enforce strict immutability by preventing attribute modification."""
        raise AttributeError(f"RecordId is immutable; cannot modify attribute {name!r}.")

    def __delattr__(self, name: str) -> None:
        """Enforce strict immutability by preventing attribute deletion."""
        raise AttributeError(f"RecordId is immutable; cannot delete attribute {name!r}.")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, RecordId):
            return self._page_id == other._page_id and self._slot_id == other._slot_id
        return False

    def __hash__(self) -> int:
        return hash((self._page_id, self._slot_id))

    def __repr__(self) -> str:
        return f"RecordId(page_id={self._page_id.value}, slot_id={self._slot_id})"

    def __str__(self) -> str:
        return f"({self._page_id.value}, {self._slot_id})"
