"""Page identifier representation and validation.

PageId represents a zero-based, non-negative integer identifier referencing
a discrete page in a Strata PageFile.
"""

from typing import Any
from strata_engine.storage.exceptions import InvalidPageIdError


class PageId:
    """Immutable, validated identifier for a page in storage.

    PageId is non-negative and directly corresponds to the sequential
    offset in a page-oriented storage file:
        file_offset = page_id * PAGE_SIZE
    """

    __slots__ = ("_value",)

    def __init__(self, value: int) -> None:
        """Initialize and validate a PageId.

        Args:
            value: Non-negative integer representing the page index.

        Raises:
            InvalidPageIdError: If value is not an integer, is a boolean, or is negative.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidPageIdError(
                f"PageId must be an integer, got {type(value).__name__}: {value!r}"
            )
        if value < 0:
            raise InvalidPageIdError(f"PageId must be non-negative, got: {value}")

        object.__setattr__(self, "_value", value)

    @property
    def value(self) -> int:
        """Return the underlying integer identifier."""
        return self._value

    def __int__(self) -> int:
        return self._value

    def __index__(self) -> int:
        return self._value

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, PageId):
            return self._value == other._value
        if isinstance(other, int) and not isinstance(other, bool):
            return self._value == other
        return False

    def __hash__(self) -> int:
        return hash(self._value)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, PageId):
            return self._value < other._value
        if isinstance(other, int) and not isinstance(other, bool):
            return self._value < other
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, PageId):
            return self._value <= other._value
        if isinstance(other, int) and not isinstance(other, bool):
            return self._value <= other
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, PageId):
            return self._value > other._value
        if isinstance(other, int) and not isinstance(other, bool):
            return self._value > other
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, PageId):
            return self._value >= other._value
        if isinstance(other, int) and not isinstance(other, bool):
            return self._value >= other
        return NotImplemented

    def __repr__(self) -> str:
        return f"PageId({self._value})"

    def __str__(self) -> str:
        return str(self._value)


def validate_page_id(page_id: Any) -> PageId:
    """Validate and return a PageId instance from a PageId or integer.

    Args:
        page_id: PageId instance or raw non-negative integer.

    Returns:
        Validated PageId instance.

    Raises:
        InvalidPageIdError: If page_id is not a valid non-negative integer.
    """
    if isinstance(page_id, PageId):
        return page_id
    return PageId(page_id)
