"""Immutable planning-level ORDER BY specification."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrderBy:
    """One unresolved-against-schema ordering request for a plan."""

    column_name: str
    descending: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.column_name, str):
            raise TypeError(
                f"column_name must be a str, got {type(self.column_name).__name__}."
            )
        if type(self.descending) is not bool:
            raise TypeError(
                f"descending must be a bool, got {type(self.descending).__name__}."
            )
