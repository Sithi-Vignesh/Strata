"""Immutable lexical tokens for the Phase 8 SQL subset."""

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """Kinds of tokens recognized by the SQL lexer."""

    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    IS = auto()
    NOT = auto()
    NULL = auto()
    TRUE = auto()
    FALSE = auto()

    IDENTIFIER = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()

    STAR = auto()
    COMMA = auto()
    SEMICOLON = auto()
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
