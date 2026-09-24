"""Hand-written lexer for the deliberately small SQL grammar."""

from strata_engine.sql.exceptions import SQLLexError
from strata_engine.sql.token import Token, TokenType


_KEYWORDS: dict[str, TokenType] = {
    "SELECT": TokenType.SELECT,
    "FROM": TokenType.FROM,
    "WHERE": TokenType.WHERE,
    "IS": TokenType.IS,
    "NOT": TokenType.NOT,
    "AND": TokenType.AND,
    "OR": TokenType.OR,
    "NULL": TokenType.NULL,
    "TRUE": TokenType.TRUE,
    "FALSE": TokenType.FALSE,
    "ORDER": TokenType.ORDER,
    "BY": TokenType.BY,
    "ASC": TokenType.ASC,
    "DESC": TokenType.DESC,
    "LIMIT": TokenType.LIMIT,
    "OFFSET": TokenType.OFFSET,
    "GROUP": TokenType.GROUP,
    "JOIN": TokenType.JOIN,
    "INNER": TokenType.INNER,
    "ON": TokenType.ON,
}


class Lexer:
    """Convert one SQL statement in the supported subset into immutable tokens."""

    def __init__(self, sql: str) -> None:
        if not isinstance(sql, str):
            raise TypeError(f"Expected SQL string, got {type(sql).__name__}.")
        self._sql = sql
        self._position = 0
        self._tokens: list[Token] = []

    def tokenize(self) -> tuple[Token, ...]:
        """Tokenize SQL text and append one EOF token."""
        while self._position < len(self._sql):
            char = self._sql[self._position]
            if char in " \t\n\r":
                self._position += 1
            elif self._is_identifier_start(char):
                self._identifier()
            elif char.isdigit() or (char == "-" and self._next_is_digit()):
                self._number()
            elif char == "'":
                self._string()
            elif char == "-":
                self._error("Unexpected character '-'")
            else:
                self._punctuation()

        self._tokens.append(Token(TokenType.EOF, "", None, self._position))
        return tuple(self._tokens)

    @staticmethod
    def _is_identifier_start(char: str) -> bool:
        return char.isascii() and (char.isalpha() or char == "_")

    @staticmethod
    def _is_identifier_part(char: str) -> bool:
        return char.isascii() and (char.isalnum() or char == "_")

    def _next_is_digit(self) -> bool:
        return self._position + 1 < len(self._sql) and self._sql[self._position + 1].isdigit()

    def _identifier(self) -> None:
        start = self._position
        self._position += 1
        while self._position < len(self._sql) and self._is_identifier_part(self._sql[self._position]):
            self._position += 1

        lexeme = self._sql[start:self._position]
        if len(lexeme) > 64:
            raise SQLLexError(f"Identifier '{lexeme}' exceeds 64 characters at position {start}.")
        token_type = _KEYWORDS.get(lexeme.upper(), TokenType.IDENTIFIER)
        literal: object | None = None
        if token_type == TokenType.TRUE:
            literal = True
        elif token_type == TokenType.FALSE:
            literal = False
        self._tokens.append(Token(token_type, lexeme, literal, start))

    def _number(self) -> None:
        start = self._position
        if self._sql[self._position] == "-":
            self._position += 1
        while self._position < len(self._sql) and self._sql[self._position].isdigit():
            self._position += 1

        token_type = TokenType.INTEGER
        if self._position < len(self._sql) and self._sql[self._position] == ".":
            self._position += 1
            decimal_start = self._position
            while self._position < len(self._sql) and self._sql[self._position].isdigit():
                self._position += 1
            if self._position == decimal_start:
                self._invalid_number(start)
            token_type = TokenType.FLOAT

        if self._position < len(self._sql):
            following = self._sql[self._position]
            if self._is_identifier_start(following) or following == ".":
                self._invalid_number(start)

        lexeme = self._sql[start:self._position]
        literal: object = int(lexeme) if token_type == TokenType.INTEGER else float(lexeme)
        self._tokens.append(Token(token_type, lexeme, literal, start))

    def _invalid_number(self, start: int) -> None:
        end = self._position
        while end < len(self._sql) and not self._sql[end].isspace() and self._sql[end] not in ",;*<>=!":
            end += 1
        raise SQLLexError(f"Invalid numeric literal '{self._sql[start:end]}' at position {start}.")

    def _string(self) -> None:
        start = self._position
        self._position += 1
        parts: list[str] = []
        while self._position < len(self._sql):
            char = self._sql[self._position]
            if char == "'":
                if self._position + 1 < len(self._sql) and self._sql[self._position + 1] == "'":
                    parts.append("'")
                    self._position += 2
                    continue
                self._position += 1
                lexeme = self._sql[start:self._position]
                self._tokens.append(Token(TokenType.STRING, lexeme, "".join(parts), start))
                return
            parts.append(char)
            self._position += 1
        raise SQLLexError(f"Unterminated string literal at position {start}.")

    def _punctuation(self) -> None:
        start = self._position
        remaining = self._sql[start:]
        two_char_tokens = {
            "<=": TokenType.LESS_EQUAL,
            ">=": TokenType.GREATER_EQUAL,
            "<>": TokenType.NOT_EQUAL,
            "!=": TokenType.NOT_EQUAL,
            "==": TokenType.EQUAL,
        }
        for lexeme, token_type in two_char_tokens.items():
            if remaining.startswith(lexeme):
                self._tokens.append(Token(token_type, lexeme, None, start))
                self._position += 2
                return

        one_char_tokens = {
            "*": TokenType.STAR,
            ".": TokenType.DOT,
            ",": TokenType.COMMA,
            ";": TokenType.SEMICOLON,
            "(": TokenType.LEFT_PAREN,
            ")": TokenType.RIGHT_PAREN,
            "=": TokenType.EQUAL,
            "<": TokenType.LESS,
            ">": TokenType.GREATER,
        }
        char = self._sql[start]
        if char in one_char_tokens:
            self._tokens.append(Token(one_char_tokens[char], char, None, start))
            self._position += 1
            return
        self._error(f"Unexpected character '{char}'")

    def _error(self, message: str) -> None:
        raise SQLLexError(f"{message} at position {self._position}.")
