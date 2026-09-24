"""Recursive-descent parser for the small Phase 8 SELECT grammar."""

from collections.abc import Sequence

from strata_engine.sql.ast import (
    AndExpression,
    AggregateCall,
    AggregateList,
    GroupedAggregateList,
    QualifiedIdentifier,
    JoinClause,
    ColumnList,
    ComparisonExpression,
    IsNullExpression,
    NotExpression,
    OrderByItem,
    OrExpression,
    SQLPredicate,
    SelectAll,
    SelectStatement,
    InsertStatement,
    ColumnDefinition,
    CreateTableStatement,
    Statement,
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
_INSERT_LITERALS = _LITERALS | {TokenType.NULL}
_AGGREGATE_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class Parser:
    """Parse a token sequence into exactly one unresolved SQL statement."""

    def __init__(self, tokens: Sequence[Token]) -> None:
        if not isinstance(tokens, Sequence) or isinstance(tokens, (str, bytes)):
            raise TypeError(f"Expected sequence of Token objects, got {type(tokens).__name__}.")
        if not all(isinstance(token, Token) for token in tokens):
            raise TypeError("Parser tokens must all be Token instances.")
        self._tokens = tuple(tokens)
        if not self._tokens or self._tokens[-1].type != TokenType.EOF:
            raise SQLParseError("Token sequence must terminate with EOF.")
        self._current = 0

    def parse(self) -> Statement:
        """Parse one supported statement followed by EOF."""
        if self._peek().type == TokenType.SELECT:
            statement = self._select_statement()
        elif self._peek().type == TokenType.INSERT:
            statement = self._insert_statement()
        elif self._peek().type == TokenType.CREATE:
            statement = self._create_table_statement()
        else:
            self._raise_expected("SELECT, INSERT, or CREATE")

        self._match(TokenType.SEMICOLON)
        self._consume(TokenType.EOF, "end of statement")
        if self._current != len(self._tokens):
            self._raise_expected("end of token stream")
        return statement

    def _select_statement(self) -> SelectStatement:
        """Parse one SELECT statement without consuming its terminator."""
        self._consume(TokenType.SELECT, "SELECT")
        projection = self._projection()
        self._consume(TokenType.FROM, "FROM")
        table_name = self._consume(TokenType.IDENTIFIER, "table identifier").lexeme
        join = None
        if self._match(TokenType.INNER):
            self._consume(TokenType.JOIN, "JOIN after INNER")
            join = self._join_clause()
        elif self._match(TokenType.JOIN):
            join = self._join_clause()

        where: SQLPredicate | None = None
        if self._match(TokenType.WHERE):
            where = self._predicate()

        group_by: tuple[QualifiedIdentifier, ...] | None = None
        if self._match(TokenType.GROUP):
            self._consume(TokenType.BY, "BY after GROUP")
            group_by = self._group_by()

        if isinstance(projection, GroupedAggregateList) and group_by is None:
            token = self._peek()
            raise SQLParseError(
                f"Cannot mix ordinary projection columns and aggregate calls without GROUP BY at position {token.position}."
            )

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

        return SelectStatement(
            table_name=table_name,
            projection=projection,
            where=where,
            order_by=order_by,
            limit=limit,
            offset=offset,
            join=join,
            group_by=group_by,
        )

    def _insert_statement(self) -> InsertStatement:
        """Parse one constrained single-row INSERT statement."""
        self._consume(TokenType.INSERT, "INSERT")
        self._consume(TokenType.INTO, "INTO after INSERT")
        table_name = self._consume(TokenType.IDENTIFIER, "table identifier").lexeme
        self._consume(TokenType.VALUES, "VALUES after table identifier")
        self._consume(TokenType.LEFT_PAREN, "'(' before INSERT values")
        values = [self._consume_insert_literal()]
        while self._match(TokenType.COMMA):
            values.append(self._consume_insert_literal())
        self._consume(TokenType.RIGHT_PAREN, "')' after INSERT values")
        return InsertStatement(table_name, tuple(values))

    def _create_table_statement(self) -> CreateTableStatement:
        """Parse one minimal CREATE TABLE statement without its terminator."""
        self._consume(TokenType.CREATE, "CREATE")
        self._consume(TokenType.TABLE, "TABLE after CREATE")
        table_name = self._consume(TokenType.IDENTIFIER, "table identifier").lexeme
        self._consume(TokenType.LEFT_PAREN, "'(' before column definitions")
        columns = [self._column_definition()]
        while self._match(TokenType.COMMA):
            columns.append(self._column_definition())
        self._consume(TokenType.RIGHT_PAREN, "')' after column definitions")
        return CreateTableStatement(table_name, tuple(columns))

    def _column_definition(self) -> ColumnDefinition:
        name = self._consume(TokenType.IDENTIFIER, "column identifier").lexeme
        token = self._peek()
        type_names = {
            TokenType.TYPE_INTEGER: "INTEGER",
            TokenType.TYPE_BIGINT: "BIGINT",
            TokenType.TYPE_FLOAT: "FLOAT",
            TokenType.TYPE_BOOLEAN: "BOOLEAN",
            TokenType.TYPE_VARCHAR: "VARCHAR",
        }
        if token.type not in type_names:
            self._raise_expected("INTEGER, BIGINT, FLOAT, BOOLEAN, or VARCHAR type")
        self._advance()
        type_name = type_names[token.type]
        if type_name != "VARCHAR":
            return ColumnDefinition(name, type_name)
        self._consume(TokenType.LEFT_PAREN, "'(' after VARCHAR")
        length = self._consume(TokenType.INTEGER, "integer VARCHAR length").literal
        assert type(length) is int
        self._consume(TokenType.RIGHT_PAREN, "')' after VARCHAR length")
        return ColumnDefinition(name, type_name, length)

    def _projection(self) -> SelectAll | ColumnList | AggregateList | GroupedAggregateList:
        if self._match(TokenType.STAR):
            return SelectAll()
        items = [self._select_item()]
        while self._match(TokenType.COMMA):
            items.append(self._select_item())
        if all(isinstance(item, (str, QualifiedIdentifier)) for item in items):
            return ColumnList(tuple(items))  # type: ignore[arg-type]
        if all(isinstance(item, AggregateCall) for item in items):
            return AggregateList(tuple(items))  # type: ignore[arg-type]
        return GroupedAggregateList(tuple(items))

    def _select_item(self) -> str | QualifiedIdentifier | AggregateCall:
        name = self._consume(TokenType.IDENTIFIER, "projection column or aggregate function").lexeme
        if self._match(TokenType.DOT):
            return QualifiedIdentifier(self._consume(TokenType.IDENTIFIER, "qualified column").lexeme, name)
        if not self._match(TokenType.LEFT_PAREN):
            return name
        if name.upper() not in _AGGREGATE_FUNCTIONS:
            raise SQLParseError(f"Unsupported aggregate function '{name}'.")
        if self._match(TokenType.STAR):
            if name.upper() != "COUNT":
                raise SQLParseError(f"Only COUNT accepts '*' at position {self._peek().position}.")
            self._consume(TokenType.RIGHT_PAREN, "')' after COUNT(*)")
            return AggregateCall(name, None)
        argument = self._column_ref()
        self._consume(TokenType.RIGHT_PAREN, "')' after aggregate argument")
        return AggregateCall(
            name,
            argument.column_name if argument.qualifier is None else argument,
        )

    def _column_ref(self) -> QualifiedIdentifier:
        first = self._consume(TokenType.IDENTIFIER, "column reference").lexeme
        if self._match(TokenType.DOT):
            return QualifiedIdentifier(self._consume(TokenType.IDENTIFIER, "qualified column").lexeme, first)
        return QualifiedIdentifier(first)

    def _join_clause(self) -> JoinClause:
        right_table = self._consume(TokenType.IDENTIFIER, "joined table identifier").lexeme
        self._consume(TokenType.ON, "ON after joined table")
        left = self._column_ref()
        self._consume(TokenType.EQUAL, "'=' in JOIN ON condition")
        right = self._column_ref()
        return JoinClause(right_table, left, right)

    def _predicate(self) -> SQLPredicate:
        return self._or_expression()

    def _order_by(self) -> tuple[OrderByItem, ...]:
        items = [self._order_item()]
        while self._match(TokenType.COMMA):
            items.append(self._order_item())
        return tuple(items)

    def _group_by(self) -> tuple[QualifiedIdentifier, ...]:
        items = [self._column_ref()]
        while self._match(TokenType.COMMA):
            items.append(self._column_ref())
        return tuple(items)

    def _order_item(self) -> OrderByItem:
        ref = self._column_ref()
        descending = False
        if self._match(TokenType.DESC):
            descending = True
        else:
            self._match(TokenType.ASC)
        return OrderByItem(ref.column_name, descending, ref.qualifier)

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
        ref = self._column_ref()
        if self._match(TokenType.IS):
            is_not_null = self._match(TokenType.NOT)
            self._consume(TokenType.NULL, "NULL after IS")
            return IsNullExpression(ref.column_name, is_not_null=is_not_null, qualifier=ref.qualifier)

        token = self._peek()
        if token.type not in _COMPARISON_OPERATORS:
            self._raise_expected("comparison operator or IS")
        self._advance()
        operator = _COMPARISON_OPERATORS[token.type]
        value = self._consume_literal()
        return ComparisonExpression(ref.column_name, operator, value, ref.qualifier)

    def _consume_literal(self) -> object:
        token = self._peek()
        if token.type not in _LITERALS:
            self._raise_expected("integer, float, string, TRUE, or FALSE literal")
        self._advance()
        return token.literal

    def _consume_insert_literal(self) -> object | None:
        token = self._peek()
        if token.type not in _INSERT_LITERALS:
            self._raise_expected("integer, float, string, TRUE, FALSE, or NULL literal")
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
