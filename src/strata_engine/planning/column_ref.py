"""SQL-independent unresolved column references for join planning."""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ColumnRef:
    column_name: str
    qualifier: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.column_name, str) or not self.column_name:
            raise TypeError("column_name must be a non-empty str.")
        if self.qualifier is not None and (not isinstance(self.qualifier, str) or not self.qualifier):
            raise TypeError("qualifier must be a non-empty str or None.")
