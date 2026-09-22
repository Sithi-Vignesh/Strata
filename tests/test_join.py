"""Focused Phase 12 two-table INNER JOIN coverage."""
from pathlib import Path
import pytest
from strata_engine.catalog import Catalog, TableNotFoundError
from strata_engine.execution import NestedLoopJoin, Operator, OperatorClosedError, TableScan
from strata_engine.execution.nested_loop_join import JoinKey
from strata_engine.planning import AmbiguousColumnError, ColumnRef, JoinCondition, JoinPlan, JoinSpec, Planner, QueryRequest, TableScanPlan
from strata_engine.planning.join_plan import JoinedLayout
from strata_engine.schema import Column, ColumnNotFoundError, DataType, Schema, Tuple, TypeMismatchError
from strata_engine.sql import Binder, Lexer, Parser, SQLBindingError, SQLParseError

def _execute(catalog, sql):
    request = Binder(catalog).bind(Parser(Lexer(sql).tokenize()).parse())
    operator = Planner().plan(request).create_operator()
    with operator:
        return operator.schema.column_names, [row.values for row in operator]

@pytest.fixture
def catalog(tmp_path: Path):
    cat = Catalog(tmp_path / "database")
    users = cat.create_table("users", Schema([Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR, max_length=20), Column("active", DataType.BOOLEAN)]))
    orders = cat.create_table("orders", Schema([Column("id", DataType.INTEGER), Column("user_id", DataType.INTEGER, nullable=True), Column("total", DataType.INTEGER), Column("note", DataType.VARCHAR, nullable=True, max_length=20)]))
    users.insert([1, "Ada", True]); users.insert([2, "Ben", False]); users.insert([3, "Null", True])
    orders.insert([10, 1, 120, None]); orders.insert([11, 1, 50, "small"]); orders.insert([12, 2, 200, "large"]); orders.insert([13, None, 999, None])
    yield cat
    cat.close()

def test_join_where_order_limit_and_reversed_on(catalog):
    names, rows = _execute(catalog, "SELECT users.name, orders.total FROM users INNER JOIN orders ON orders.user_id = users.id WHERE users.active = TRUE AND orders.total > 60 ORDER BY orders.total DESC LIMIT 1")
    assert names == ("name", "total")
    assert rows == [("Ada", 120)]

def test_join_collision_labels_and_unqualified_unique(catalog):
    names, rows = _execute(catalog, "SELECT users.id, orders.id FROM users JOIN orders ON users.id = orders.user_id ORDER BY total")
    assert names == ("users_id", "orders_id")
    assert rows == [(1, 11), (1, 10), (2, 12)]

def test_join_restrictions_and_ambiguity(catalog):
    with pytest.raises(AmbiguousColumnError):
        _execute(catalog, "SELECT id FROM users JOIN orders ON users.id = orders.user_id")
    with pytest.raises(SQLBindingError):
        _execute(catalog, "SELECT * FROM users JOIN orders ON users.id = orders.user_id")
    with pytest.raises(SQLBindingError):
        _execute(catalog, "SELECT COUNT(*) FROM users JOIN orders ON users.id = orders.user_id")
    with pytest.raises(SQLBindingError):
        _execute(catalog, "SELECT users.id FROM users JOIN users ON users.id = users.id")
    with pytest.raises(SQLParseError):
        Parser(Lexer("SELECT users.id FROM users JOIN orders ON users.id > orders.user_id").tokenize()).parse()


def _joined_schema(left: Schema, right: Schema) -> Schema:
    columns = [Column(f"left_{i}", c.data_type, c.nullable, c.max_length) for i, c in enumerate(left.columns)]
    columns.extend(Column(f"right_{i}", c.data_type, c.nullable, c.max_length) for i, c in enumerate(right.columns))
    return Schema(columns)


class _Rows(Operator):
    """Small controllable child operator for join lifecycle tests."""
    def __init__(self, schema, values=(), fail_open=None, fail_next=None):
        self._schema, self._values = schema, tuple(values)
        self.fail_open, self.fail_next = fail_open, fail_next
        self.opens = self.closes = self.position = 0
        self._open = False
    @property
    def schema(self): return self._schema
    @property
    def is_open(self): return self._open
    def open(self):
        self.opens += 1
        if self.fail_open is not None: raise self.fail_open
        self.position = 0; self._open = True
    def next(self):
        if not self._open: raise OperatorClosedError("closed")
        if self.fail_next is not None: raise self.fail_next
        if self.position == len(self._values): return None
        value = self._values[self.position]; self.position += 1
        return Tuple(value, self._schema)
    def close(self): self.closes += 1; self._open = False


def test_nested_loop_join_execution_lifecycle_and_rescan(catalog):
    users, orders = catalog.get_table("users"), catalog.get_table("orders")
    join = NestedLoopJoin(TableScan(users), TableScan(orders), JoinKey(0, 1), _joined_schema(users.schema, orders.schema))
    with pytest.raises(OperatorClosedError): join.next()
    join.open()
    assert [r.values for r in join] == [
        (1, "Ada", True, 10, 1, 120, None), (1, "Ada", True, 11, 1, 50, "small"), (2, "Ben", False, 12, 2, 200, "large")]
    assert join.next() is None and join.next() is None
    assert join.schema.column_names == ("left_0", "left_1", "left_2", "right_0", "right_1", "right_2", "right_3")
    join.open(); assert join.next().values[:2] == (1, "Ada")
    join.close(); join.close()
    with pytest.raises(OperatorClosedError): join.next()


def test_nested_loop_join_null_empty_boolean_and_varchar_contracts():
    nullable = Schema([Column("key", DataType.INTEGER, nullable=True)])
    for left_values, right_values in ((((None,),), ((None,),)), (((None,),), ((1,),)), (((1,),), ((None,),)), ((), ((1,),)), (((1,),), ())):
        join = NestedLoopJoin(_Rows(nullable, left_values), _Rows(nullable, right_values), JoinKey(0, 0), _joined_schema(nullable, nullable))
        with join: assert join.next() is None
    for data_type, value in ((DataType.BOOLEAN, True), (DataType.VARCHAR, "same")):
        schema = Schema([Column("key", data_type, max_length=20 if data_type is DataType.VARCHAR else None)])
        join = NestedLoopJoin(_Rows(schema, ((value,),)), _Rows(schema, ((value,),)), JoinKey(0, 0), _joined_schema(schema, schema))
        with join: assert join.next().values == (value, value)


@pytest.mark.parametrize("site", ["left_open", "right_open", "left_next", "right_next", "right_reopen"])
def test_nested_loop_join_failure_cleanup_preserves_original_error(site):
    schema, failure = Schema([Column("key", DataType.INTEGER)]), RuntimeError(site)
    left = _Rows(schema, ((1,), (2,)), fail_open=failure if site == "left_open" else None, fail_next=failure if site == "left_next" else None)
    right = _Rows(schema, ((1,),), fail_open=failure if site == "right_open" else None, fail_next=failure if site == "right_next" else None)
    if site == "right_reopen":
        class ReopenFails(_Rows):
            def open(self):
                super().open()
                if self.opens == 2: raise failure
        right = ReopenFails(schema, ((1,),))
    join = NestedLoopJoin(left, right, JoinKey(0, 0), _joined_schema(schema, schema))
    with pytest.raises(RuntimeError) as raised:
        if site.endswith("open") and site != "right_reopen": join.open()
        else:
            join.open()
            while join.next() is not None: pass
    assert raised.value is failure and left.closes >= 1 and right.closes >= 1 and not join.is_open


def _plans(catalog):
    return TableScanPlan(catalog.get_table("users")), TableScanPlan(catalog.get_table("orders"))


def test_join_plan_schema_layout_and_fresh_operator_trees(catalog, monkeypatch):
    left, right = _plans(catalog)
    condition = JoinCondition(ColumnRef("id", "users"), ColumnRef("user_id", "orders"))
    def fail_create_operator(self):
        raise AssertionError("planning must not construct child operators")
    monkeypatch.setattr(TableScanPlan, "create_operator", fail_create_operator)
    plan = JoinPlan(left, right, condition, "users", "orders")
    assert plan.schema.column_names == ("_j_left_0", "_j_left_1", "_j_left_2", "_j_right_0", "_j_right_1", "_j_right_2", "_j_right_3")
    assert [(c.data_type, c.nullable, c.max_length) for c in plan.schema.columns] == [(c.data_type, c.nullable, c.max_length) for c in left.schema.columns + right.schema.columns]
    with pytest.raises(AssertionError, match="planning must not construct"):
        plan.create_operator()
    monkeypatch.undo()
    first, second = plan.create_operator(), plan.create_operator()
    assert isinstance(first, NestedLoopJoin) and first is not second and first.left is not second.left and not first.is_open
    with pytest.raises(TypeError): JoinPlan(object(), right, condition, "users", "orders")
    with pytest.raises(TypeError): JoinPlan(left, object(), condition, "users", "orders")


def test_on_resolution_layout_and_type_contracts(catalog):
    left, right = _plans(catalog)
    forward = JoinPlan(left, right, JoinCondition(ColumnRef("id", "users"), ColumnRef("user_id", "orders")), "users", "orders")
    reverse = JoinPlan(left, right, JoinCondition(ColumnRef("user_id", "orders"), ColumnRef("id", "users")), "users", "orders")
    assert forward._key == reverse._key == JoinKey(0, 1)
    layout = forward.layout
    assert layout.resolve(ColumnRef("NAME", "UsErS")).index == 1
    assert layout.resolve(ColumnRef("total")).internal_name == "_j_right_2"
    assert layout.resolve(ColumnRef("USER_ID", "ORDERS")).column is right.schema["user_id"]
    for ref, error in ((ColumnRef("id"), AmbiguousColumnError), (ColumnRef("missing"), ColumnNotFoundError), (ColumnRef("id", "other"), ColumnNotFoundError), (ColumnRef("missing", "users"), ColumnNotFoundError)):
        with pytest.raises(error): layout.resolve(ref)
    for condition in (JoinCondition(ColumnRef("id", "users"), ColumnRef("name", "users")), JoinCondition(ColumnRef("id", "orders"), ColumnRef("user_id", "orders"))):
        with pytest.raises(ValueError): JoinPlan(left, right, condition, "users", "orders")
    with pytest.raises(TypeMismatchError): JoinPlan(left, right, JoinCondition(ColumnRef("name", "users"), ColumnRef("user_id", "orders")), "users", "orders")


@pytest.mark.parametrize("data_type", [DataType.INTEGER, DataType.BIGINT, DataType.FLOAT, DataType.BOOLEAN, DataType.VARCHAR])
def test_join_plan_accepts_exact_types_and_varchar_lengths(tmp_path, data_type):
    cat = Catalog(tmp_path / data_type.value)
    a = cat.create_table("a", Schema([Column("key", data_type, max_length=20 if data_type is DataType.VARCHAR else None)]))
    b = cat.create_table("b", Schema([Column("key", data_type, max_length=100 if data_type is DataType.VARCHAR else None)]))
    JoinPlan(TableScanPlan(a), TableScanPlan(b), JoinCondition(ColumnRef("key", "a"), ColumnRef("key", "b")), "a", "b")
    cat.close()


@pytest.mark.parametrize("left_type,right_type", [(DataType.INTEGER, DataType.BIGINT), (DataType.INTEGER, DataType.FLOAT), (DataType.VARCHAR, DataType.INTEGER)])
def test_join_plan_rejects_implicit_coercion(tmp_path, left_type, right_type):
    cat = Catalog(tmp_path / f"{left_type.value}_{right_type.value}")
    a = cat.create_table("a", Schema([Column("key", left_type, max_length=20 if left_type is DataType.VARCHAR else None)]))
    b = cat.create_table("b", Schema([Column("key", right_type, max_length=20 if right_type is DataType.VARCHAR else None)]))
    with pytest.raises(TypeMismatchError): JoinPlan(TableScanPlan(a), TableScanPlan(b), JoinCondition(ColumnRef("key", "a"), ColumnRef("key", "b")), "a", "b")
    cat.close()


def test_joined_where_order_limit_projection_and_ambiguity_contracts(catalog):
    base = "FROM users JOIN orders ON users.id = orders.user_id"
    assert _execute(catalog, f"SELECT users.name, orders.total {base} WHERE orders.total > 100")[1] == [("Ada", 120), ("Ben", 200)]
    assert _execute(catalog, f"SELECT users.name, orders.total {base} WHERE users.active = TRUE AND orders.total >= 50")[1] == [("Ada", 120), ("Ada", 50)]
    assert _execute(catalog, f"SELECT users.name {base} WHERE orders.note IS NULL")[1] == [("Ada",)]
    assert _execute(catalog, f"SELECT users.name {base} WHERE orders.note IS NOT NULL")[1] == [("Ada",), ("Ben",)]
    assert _execute(catalog, f"SELECT users.name {base} WHERE NOT (orders.total < 10 OR users.active = FALSE)")[1] == [("Ada",), ("Ada",)]
    assert _execute(catalog, f"SELECT users.name {base} ORDER BY orders.total DESC")[1] == [("Ben",), ("Ada",), ("Ada",)]
    assert _execute(catalog, f"SELECT users.name, orders.total {base} ORDER BY orders.total DESC, users.name ASC LIMIT 1 OFFSET 1")[1] == [("Ada", 120)]
    assert _execute(catalog, f"SELECT users.name {base} LIMIT 0")[1] == []
    for query in (f"SELECT id {base}", f"SELECT users.name {base} WHERE id = 1", f"SELECT users.name {base} ORDER BY id"):
        with pytest.raises(AmbiguousColumnError): _execute(catalog, query)


def test_projection_names_long_names_parser_rejections_and_api(catalog, tmp_path):
    base = "FROM users JOIN orders ON users.id = orders.user_id"
    assert _execute(catalog, f"SELECT users.name, orders.total {base}")[0] == ("name", "total")
    names, _ = _execute(catalog, f"SELECT users.id, orders.id {base}")
    assert names == ("users_id", "orders_id") and all(not name.startswith("_j_") for name in names)
    cat = Catalog(tmp_path / "long")
    left_name, right_name, column = "l" * 63, "r" * 63, "c" * 64
    left = cat.create_table(left_name, Schema([Column(column, DataType.INTEGER)])); right = cat.create_table(right_name, Schema([Column(column, DataType.INTEGER)])); left.insert([1]); right.insert([1])
    names, rows = _execute(cat, f"SELECT {left_name}.{column}, {right_name}.{column} FROM {left_name} JOIN {right_name} ON {left_name}.{column} = {right_name}.{column}")
    assert rows == [(1, 1)] and len(set(names)) == 2 and all(len(name) <= 64 for name in names)
    cat.close()
    assert Parser(Lexer("select users.name from users inner join orders on users.id = orders.user_id order by orders.total desc, users.name asc").tokenize()).parse().join is not None
    for name in ("join_date", "inner_value", "online"):
        assert Parser(Lexer(f"SELECT {name} FROM users").tokenize()).parse().table_name == "users"
    # JOIN ON accepts only column_ref = column_ref; literal operands fail in parsing.
    for sql in ("SELECT users. FROM users", "SELECT .users FROM users", "SELECT users..id FROM users", "SELECT users.id FROM users JOIN orders ON users.id > orders.user_id", "SELECT users.id FROM users JOIN orders ON 1 = orders.user_id", "SELECT users.id FROM users JOIN orders ON users.id = 1", "SELECT users.id FROM users JOIN orders ON users.id = orders.user_id JOIN users ON users.id = users.id"):
        with pytest.raises(SQLParseError): Parser(Lexer(sql).tokenize()).parse()
    for sql in ("SELECT * FROM users JOIN orders ON users.id = orders.user_id", "SELECT COUNT(*) FROM users JOIN orders ON users.id = orders.user_id", "SELECT users.id FROM users JOIN users ON users.id = users.id", "SELECT users.id FROM users JOIN missing ON users.id = missing.id"):
        with pytest.raises((SQLBindingError, ColumnNotFoundError, TableNotFoundError)): Binder(catalog).bind(Parser(Lexer(sql).tokenize()).parse())
    request = QueryRequest(catalog.get_table("users"), None, ("name",), None, 1, 0)
    assert request.projection == ("name",) and request.join is request.joined_where is request.join_projection is request.join_order_by is None
    from strata_engine import AmbiguousColumnError as PublicAmbiguous, ColumnRef as PublicRef, JoinCondition as PublicCondition, JoinPlan as PublicPlan, JoinSpec as PublicSpec, NestedLoopJoin as PublicJoin
    assert (PublicJoin, PublicRef, PublicCondition, PublicSpec, PublicPlan, PublicAmbiguous) == (NestedLoopJoin, ColumnRef, JoinCondition, JoinSpec, JoinPlan, AmbiguousColumnError)
    import strata_engine
    assert not hasattr(strata_engine, "JoinKey")
