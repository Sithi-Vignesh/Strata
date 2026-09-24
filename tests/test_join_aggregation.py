"""Phase 14 composition coverage for aggregation over a two-table INNER JOIN."""

from pathlib import Path

import pytest

from strata_engine.catalog import Catalog
from strata_engine.planning import AggregatePlan, AmbiguousColumnError, JoinPlan, JoinProjectionPlan, LimitPlan, Planner, SortPlan
from strata_engine.schema import Column, DataType, Schema
from strata_engine.sql import Binder, Lexer, Parser, SQLBindingError, SQLParseError


def _request(catalog: Catalog, sql: str):
    return Binder(catalog).bind(Parser(Lexer(sql).tokenize()).parse())


def _execute(catalog: Catalog, sql: str):
    operator = Planner().plan(_request(catalog, sql)).create_operator()
    with operator:
        return operator.schema.column_names, [row.values for row in operator]


@pytest.fixture
def catalog(tmp_path: Path):
    instance = Catalog(tmp_path / "database")
    users = instance.create_table(
        "users",
        Schema([
            Column("id", DataType.INTEGER),
            Column("country", DataType.VARCHAR, nullable=True, max_length=16),
            Column("age", DataType.INTEGER, nullable=True),
        ]),
    )
    orders = instance.create_table(
        "orders",
        Schema([
            Column("id", DataType.INTEGER),
            Column("user_id", DataType.INTEGER, nullable=True),
            Column("status", DataType.VARCHAR, nullable=True, max_length=16),
            Column("total", DataType.INTEGER, nullable=True),
        ]),
    )
    users.insert([1, "IN", 30]); users.insert([2, "US", 40]); users.insert([3, None, 50])
    orders.insert([10, 1, "open", 100]); orders.insert([11, 1, "closed", None])
    orders.insert([12, 2, "open", 200]); orders.insert([13, None, "open", 999])
    yield instance
    instance.close()


def test_global_join_aggregation_qualified_unqualified_and_names(catalog):
    names, rows = _execute(
        catalog,
        "SELECT COUNT(*), COUNT(users.id), COUNT(orders.id), SUM(total), AVG(orders.total), "
        "MIN(users.age), MAX(orders.total) FROM users JOIN orders ON users.id = orders.user_id",
    )
    assert names == (
        "count_star", "count_users_id", "count_orders_id", "sum_total",
        "avg_orders_total", "min_users_age", "max_orders_total",
    )
    assert rows == [(3, 3, 3, 300, 150.0, 30, 200)]


def test_grouped_join_aggregation_preserves_select_order_where_order_and_limit(catalog):
    names, rows = _execute(
        catalog,
        "SELECT COUNT(*), users.country, AVG(orders.total) FROM users "
        "JOIN orders ON users.id = orders.user_id WHERE orders.status = 'open' "
        "GROUP BY users.country ORDER BY count_star DESC, country ASC LIMIT 1 OFFSET 0",
    )
    assert names == ("count_star", "country", "avg_orders_total")
    assert rows == [(1, "IN", 100.0)]


def test_grouped_join_multiple_keys_null_and_all_null_aggregate_input(catalog):
    names, rows = _execute(
        catalog,
        "SELECT orders.status, users.country, COUNT(*), SUM(orders.total) FROM users "
        "JOIN orders ON users.id = orders.user_id GROUP BY users.country, orders.status "
        "ORDER BY country, status",
    )
    assert names == ("status", "country", "count_star", "sum_orders_total")
    assert rows == [("closed", "IN", 1, None), ("open", "IN", 1, 100), ("open", "US", 1, 200)]


def test_empty_join_global_and_grouped_semantics(catalog):
    assert _execute(
        catalog,
        "SELECT COUNT(*), COUNT(orders.total), SUM(orders.total), AVG(orders.total), "
        "MIN(orders.total), MAX(orders.total) FROM users JOIN orders ON users.id = orders.user_id "
        "WHERE orders.total > 1000",
    )[1] == [(0, 0, None, None, None, None)]
    assert _execute(
        catalog,
        "SELECT users.country, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id "
        "WHERE orders.total > 1000 GROUP BY users.country",
    )[1] == []


@pytest.mark.parametrize(
    "sql, error",
    [
        ("SELECT COUNT(id) FROM users JOIN orders ON users.id = orders.user_id", AmbiguousColumnError),
        ("SELECT id, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id GROUP BY id", AmbiguousColumnError),
        ("SELECT users.country, orders.status, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id GROUP BY users.country", SQLBindingError),
        ("SELECT users.country FROM users JOIN orders ON users.id = orders.user_id GROUP BY users.country", SQLBindingError),
        ("SELECT users.country, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id GROUP BY users.country ORDER BY users.country", SQLBindingError),
        ("SELECT users.country, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id GROUP BY users.country ORDER BY COUNT(*)", SQLParseError),
    ],
)
def test_join_aggregate_rejections(catalog, sql, error):
    with pytest.raises(error):
        _execute(catalog, sql)


def test_join_aggregate_plan_shape_has_no_join_projection(catalog):
    plan = Planner().plan(_request(
        catalog,
        "SELECT users.country, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id "
        "GROUP BY users.country ORDER BY count_star DESC LIMIT 2",
    ))
    assert isinstance(plan, LimitPlan)
    assert isinstance(plan.child, SortPlan)
    assert isinstance(plan.child.child, AggregatePlan)
    assert isinstance(plan.child.child.child, JoinPlan)
    assert not isinstance(plan.child.child.child, JoinProjectionPlan)


def test_join_grouping_preserves_null_key(catalog):
    catalog.get_table("orders").insert([14, 3, "open", 50])
    names, rows = _execute(
        catalog,
        "SELECT users.country, COUNT(*) FROM users JOIN orders ON users.id = orders.user_id "
        "GROUP BY users.country ORDER BY country",
    )
    assert names == ("country", "count_star")
    assert rows == [("IN", 2), ("US", 1), (None, 1)]


def test_qualified_aggregate_name_is_deterministically_truncated(tmp_path: Path):
    instance = Catalog(tmp_path / "long")
    left_name, right_name, column_name = "l" * 63, "r" * 63, "c" * 64
    left = instance.create_table(left_name, Schema([Column(column_name, DataType.INTEGER)]))
    right = instance.create_table(right_name, Schema([Column(column_name, DataType.INTEGER)]))
    left.insert([1]); right.insert([1])
    names, rows = _execute(
        instance,
        f"SELECT COUNT({left_name}.{column_name}) FROM {left_name} JOIN {right_name} "
        f"ON {left_name}.{column_name} = {right_name}.{column_name}",
    )
    assert rows == [(1,)]
    assert names == ("count_" + f"{left_name}_{column_name}"[:58],)
    assert len(names[0]) == 64
    instance.close()


def test_ordinary_join_still_uses_join_projection(catalog):
    plan = Planner().plan(_request(
        catalog,
        "SELECT users.country, orders.total FROM users JOIN orders ON users.id = orders.user_id",
    ))
    assert isinstance(plan, JoinProjectionPlan)
