"""Focused tests for Phase 8 SQL lexical analysis."""

from dataclasses import FrozenInstanceError

import pytest

from strata_engine.sql import Lexer, SQLLexError, TokenType


def test_lexer_keywords_preserve_identifier_spelling_and_literals() -> None:
    tokens = Lexer("sElEcT Name FROM Users WHERE active = TRUE").tokenize()

    assert [token.type for token in tokens] == [
        TokenType.SELECT,
        TokenType.IDENTIFIER,
        TokenType.FROM,
        TokenType.IDENTIFIER,
        TokenType.WHERE,
        TokenType.IDENTIFIER,
        TokenType.EQUAL,
        TokenType.TRUE,
        TokenType.EOF,
    ]
    assert tokens[1].lexeme == "Name"
    assert tokens[3].lexeme == "Users"
    assert tokens[7].literal is True
    assert tokens[-1].position == len("sElEcT Name FROM Users WHERE active = TRUE")


def test_lexer_recognizes_insert_keywords_case_insensitively() -> None:
    tokens = Lexer("iNsErT InTo users VaLuEs (1, NULL)").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.INSERT,
        TokenType.INTO,
        TokenType.IDENTIFIER,
        TokenType.VALUES,
        TokenType.LEFT_PAREN,
        TokenType.INTEGER,
        TokenType.COMMA,
        TokenType.NULL,
        TokenType.RIGHT_PAREN,
        TokenType.EOF,
    ]


def test_lexer_recognizes_punctuation_and_all_comparison_spellings() -> None:
    tokens = Lexer("*,; = == != <> < <= > >=").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.STAR,
        TokenType.COMMA,
        TokenType.SEMICOLON,
        TokenType.EQUAL,
        TokenType.EQUAL,
        TokenType.NOT_EQUAL,
        TokenType.NOT_EQUAL,
        TokenType.LESS,
        TokenType.LESS_EQUAL,
        TokenType.GREATER,
        TokenType.GREATER_EQUAL,
        TokenType.EOF,
    ]


def test_lexer_recognizes_boolean_keywords_and_predicate_parentheses() -> None:
    tokens = Lexer("a AnD b oR NOT (c)").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.IDENTIFIER,
        TokenType.AND,
        TokenType.IDENTIFIER,
        TokenType.OR,
        TokenType.NOT,
        TokenType.LEFT_PAREN,
        TokenType.IDENTIFIER,
        TokenType.RIGHT_PAREN,
        TokenType.EOF,
    ]


def test_lexer_keeps_boolean_keyword_prefixes_as_identifiers() -> None:
    tokens = Lexer("android or_value notify and_value oracle").tokenize()
    assert [token.type for token in tokens] == [TokenType.IDENTIFIER] * 5 + [TokenType.EOF]


def test_lexer_recognizes_ordering_and_limit_keywords_as_whole_words() -> None:
    tokens = Lexer("oRdEr BY age aSc, score dEsC LIMIT 10 OFFSET 2").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.ORDER,
        TokenType.BY,
        TokenType.IDENTIFIER,
        TokenType.ASC,
        TokenType.COMMA,
        TokenType.IDENTIFIER,
        TokenType.DESC,
        TokenType.LIMIT,
        TokenType.INTEGER,
        TokenType.OFFSET,
        TokenType.INTEGER,
        TokenType.EOF,
    ]
    prefixes = Lexer("ordered ordering bypass ascending description limiter offset_value").tokenize()
    assert [token.type for token in prefixes] == [TokenType.IDENTIFIER] * 7 + [TokenType.EOF]


def test_lexer_recognizes_numeric_string_boolean_and_null_literals() -> None:
    tokens = Lexer("0 -1 3.14 -2.5 'Alice' '' 'O''Brien' FALSE NULL").tokenize()
    assert [token.literal for token in tokens[:-1]] == [
        0,
        -1,
        3.14,
        -2.5,
        "Alice",
        "",
        "O'Brien",
        False,
        None,
    ]
    assert [token.type for token in tokens[:-1]] == [
        TokenType.INTEGER,
        TokenType.INTEGER,
        TokenType.FLOAT,
        TokenType.FLOAT,
        TokenType.STRING,
        TokenType.STRING,
        TokenType.STRING,
        TokenType.FALSE,
        TokenType.NULL,
    ]


def test_lexer_ignores_multiline_whitespace() -> None:
    tokens = Lexer("SELECT\n*\r\nFROM\tusers;").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.SELECT,
        TokenType.STAR,
        TokenType.FROM,
        TokenType.IDENTIFIER,
        TokenType.SEMICOLON,
        TokenType.EOF,
    ]


@pytest.mark.parametrize("sql", ["SELECT @ FROM users", "SELECT * FROM users WHERE x ! 1", "SELECT * FROM users WHERE x - 1"])
def test_lexer_rejects_illegal_characters_and_bare_minus(sql: str) -> None:
    with pytest.raises(SQLLexError):
        Lexer(sql).tokenize()


@pytest.mark.parametrize("sql", ["SELECT * FROM users WHERE x = 1e10", "SELECT * FROM users WHERE x = 1.", "SELECT * FROM users WHERE x = 1.2.3"])
def test_lexer_rejects_unsupported_numeric_forms(sql: str) -> None:
    with pytest.raises(SQLLexError):
        Lexer(sql).tokenize()


def test_lexer_rejects_unterminated_string_and_long_identifier() -> None:
    with pytest.raises(SQLLexError):
        Lexer("SELECT 'unterminated FROM users").tokenize()
    with pytest.raises(SQLLexError):
        Lexer(f"SELECT {'a' * 65} FROM users").tokenize()


def test_token_is_immutable() -> None:
    token = Lexer("SELECT").tokenize()[0]
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        token.lexeme = "select"  # type: ignore[misc]
