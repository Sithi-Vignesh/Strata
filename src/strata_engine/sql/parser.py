"""Recursive-descent parser for the small Phase 8 SELECT grammar."""

from collections.abc import Sequence

from strata_engine.sql.ast import (
    AndExpression,
    AggregateCall,
    AggregateList,
    ColumnList,
    ComparisonExpression,
    IsNullExpression,
    NotExpression,
    OrderByItem,
    OrExpression,
    SQLPredicate,
    SelectAll,
    SelectStatement,
)
from strata_engine.sql.exceptions import SQLParseError
from strata_engine.sql.token import Token, TokenType


_COMPARISON_OPERATORS: dict[TokenType, str] = {
    TokenType.EQUAL: "=",
    TokenType.NOT_EQUAL: "!=",
    TokenType.LESS: "<",
    TokenType.LESS_EQUAL: "<=",
    TokenType.GREATER: ">",
    TokenType.GREATER_EQUAL: ">=",
}
_LITERALS = {TokenType.INTEGER, TokenType.FLOAT, TokenType.STRING, TokenType.TRUE, TokenType.FALSE}
_AGGREGATE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class Parser:
    """Parse a token sequence into exactly one unresolved SelectStatement."""

    def __init__(self, tokens: Sequence[Token]) -> None:
        if not isinstance(tokens, Sequence) or isinstance(tokens, (str, bytes)):
            raise TypeError(f"Expected sequence of Token objects, got {type(tokens).__name__}.")
        if not all(isinstance(token, Token) for token in tokens):
            raise TypeError("Parser tokens must all be Token instances.")
        self._tokens = tuple(tokens)
        if not self._tokens or self._tokens[-1].type != TokenType.EOF:
            raise SQLParseError("Token sequence must terminate with EOF.")
        self._current = 0

    def parse(self) -> SelectStatement:
        """Parse one SELECT statement followed by EOF."""
        self._consume(TokenType.SELECT, "SELECT")
        projection = self._projection()
        self._consume(TokenType.FROM, "FROM")
        table_name = self._consume(TokenType.IDENTIFIER, "table identifier").lexeme

        where: SQLPredicate | None = None
        if self._match(TokenType.WHERE):
            where = self._predicate()

        order_by: tuple[OrderByItem, ...] | None = None
        if self._match(TokenType.ORDER):
            self._consume(TokenType.BY, "BY after ORDER")
            order_by = self._order_by()

        limit: int | None = None
        offset = 0
        if self._match(TokenType.LIMIT):
            limit = self._consume_non_negative_integer("LIMIT value")
            if self._match(TokenType.OFFSET):
                offset = self._consume_non_negative_integer("OFFSET value")

        self._match(TokenType.SEMICOLON)
        self._consume(TokenType.EOF, "end of statement")
        if self._current != len(self._tokens):
            self._raise_expected("end of token stream")
        return SelectStatement(
            table_name=table_name,
            projection=projection,
            where=where,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def _projection(self) -> SelectAll | ColumnList | AggregateList:
        if self._match(TokenType.STAR):
            return SelectAll()
        items = [self._select_item()]
        while self._match(TokenType.COMMA):
            items.append(self._select_item())
        if all(isinstance(item, str) for item in items):
            return ColumnList(tuple(items))  # type: ignore[arg-type]
        if all(isinstance(item, AggregateCall) for item in items):
            return AggregateList(tuple(items))  # type: ignore[arg-type]
        token = self._peek()
        raise SQLParseError(
            f"Cannot mix ordinary projection columns and aggregate calls at position {token.position}."
        )

    def _select_item(self) -> str | AggregateCall:
        name = self._consume(TokenType.IDENTIFIER, "projection column or aggregate function").lexeme
        if not self._match(TokenType.LEFT_PAREN):
            return name
        if name.upper() not in _AGGREGATE_FUNCTIONS:
            raise SQLParseError(f"Unsupported aggregate function '{name}'.")
        if self._match(TokenType.STAR):
            if name.upper() != "COUNT":
                raise SQLParseError(f"Only COUNT accepts '*' at position {self._peek().position}.")
            self._consume(TokenType.RIGHT_PAREN, "')' after COUNT(*)")
            return AggregateCall(name, None)
        argument = self._consume(TokenType.IDENTIFIER, "aggregate source column").lexeme
        self._consume(TokenType.RIGHT_PAREN, "')' after aggregate argument")
        return AggregateCall(name, argument)

    def _predicate(self) -> SQLPredicate:
        return self._or_expression()

    def _order_by(self) -> tuple[OrderByItem, ...]:
        items = [self._order_item()]
        while self._match(TokenType.COMMA):
            items.append(self._order_item())
        return tuple(items)

    def _order_item(self) -> OrderByItem:
        column_name = self._consume(TokenType.IDENTIFIER, "ORDER BY column").lexeme
        descending = False
        if self._match(TokenType.DESC):
            descending = True
        else:
            self._match(TokenType.ASC)
        return OrderByItem(column_name, descending)

    def _consume_non_negative_integer(self, expected: str) -> int:
        token = self._peek()
        if token.type != TokenType.INTEGER or type(token.literal) is not int or token.literal < 0:
            self._raise_expected(f"non-negative integer {expected}")
        self._advance()
        return token.literal

    def _or_expression(self) -> SQLPredicate:
        predicate = self._and_expression()
        while self._match(TokenType.OR):
            predicate = OrExpression(predicate, self._and_expression())
        return predicate

    def _and_expression(self) -> SQLPredicate:
        predicate = self._not_expression()
        while self._match(TokenType.AND):
            predicate = AndExpression(predicate, self._not_expression())
        return predicate

    def _not_expression(self) -> SQLPredicate:
        if self._match(TokenType.NOT):
            return NotExpression(self._not_expression())
        return self._predicate_primary()

    def _predicate_primary(self) -> SQLPredicate:
        if self._match(TokenType.LEFT_PAREN):
            predicate = self._predicate()
            self._consume(TokenType.RIGHT_PAREN, "')' after predicate")
            return predicate
        return self._leaf_predicate()

    def _leaf_predicate(self) -> SQLPredicate:
        column_name = self._consume(TokenType.IDENTIFIER, "predicate column").lexeme
        if self._match(TokenType.IS):
            is_not_null = self._match(TokenType.NOT)
            self._consume(TokenType.NULL, "NULL after IS")
            return IsNullExpression(column_name, is_not_null=is_not_null)

        token = self._peek()
        if token.type not in _COMPARISON_OPERATORS:
            self._raise_expected("comparison operator or IS")
        self._advance()
        operator = _COMPARISON_OPERATORS[token.type]
        value = self._consume_literal()
        return ComparisonExpression(column_name, operator, value)

    def _consume_literal(self) -> object:
        token = self._peek()
        if token.type not in _LITERALS:
            self._raise_expected("integer, float, string, TRUE, or FALSE literal")
        self._advance()
        return token.literal

    def _match(self, token_type: TokenType) -> bool:
        if self._peek().type != token_type:
            return False
        self._advance()
        return True

    def _consume(self, token_type: TokenType, expected: str) -> Token:
        if self._peek().type == token_type:
            return self._advance()
        self._raise_expected(expected)

    def _advance(self) -> Token:
        token = self._peek()
        if self._current < len(self._tokens):
            self._current += 1
        return token

    def _peek(self) -> Token:
        if self._current >= len(self._tokens):
            position = self._tokens[-1].position if self._tokens else 0
            return Token(TokenType.EOF, "", None, position)
        return self._tokens[self._current]

    def _raise_expected(self, expected: str) -> None:
        token = self._peek()
        encountered = token.lexeme if token.lexeme else "EOF"
        raise SQLParseError(
            f"Expected {expected} at position {token.position}, encountered '{encountered}'."
        )
