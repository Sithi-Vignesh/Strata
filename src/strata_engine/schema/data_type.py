"""Data type definitions for Strata."""

from enum import Enum


class DataType(Enum):
    """Supported relational data types in Strata."""

    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    VARCHAR = "VARCHAR"
