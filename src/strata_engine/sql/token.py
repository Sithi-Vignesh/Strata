"""Immutable lexical tokens for the deliberately small SQL subset."""

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """Kinds of tokens recognized by the SQL lexer."""

    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    IS = auto()
    NOT = auto()
    AND = auto()
    OR = auto()
    NULL = auto()
    TRUE = auto()
    FALSE = auto()
    ORDER = auto()
    BY = auto()
    ASC = auto()
    DESC = auto()
    LIMIT = auto()
    OFFSET = auto()
    JOIN = auto()
    INNER = auto()
    ON = auto()

    IDENTIFIER = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()

    STAR = auto()
    DOT = auto()
    COMMA = auto()
    SEMICOLON = auto()
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    EQUAL = auto()
    NOT_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    EOF = auto()


@dataclass(frozen=True, slots=True)
class Token:
    """A token with original text, parsed literal, and zero-based offset."""

    type: TokenType
    lexeme: str
    literal: object | None
    position: int
