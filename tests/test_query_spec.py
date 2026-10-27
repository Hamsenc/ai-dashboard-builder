"""Test query_spec: JOIN, COUNT_DISTINCT, lọc động qua tham số URL, trần tổng limit.
Giả lập metadata bảng bằng monkeypatch bq_meta.get_table — không cần BigQuery."""

import datetime
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from datasource import bq_meta
from embeds import query_spec
from embeds.query_spec import InvalidQuerySpecError, build_queries, build_query, declared_params

SALES = "surya-495408.00_serving_sales.vw_sales"
INV = "surya-495408.00_serving_inventory.vw_inv"
TABLES = {
    SALES: {"sku": "STRING", "wh": "STRING", "order_date": "DATE", "qty": "INT64", "customer_id": "STRING"},
    INV: {"sku": "STRING", "wh": "STRING", "stock": "INT64"},
}
bq_meta.get_table = lambda c, t: (
    {"columns": [{"name": n, "type": ty} for n, ty in TABLES[t].items()]} if t in TABLES else None
)


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"phải raise {exc.__name__}")


def test_legacy_spec_still_builds():
    plan = build_query(None, {"table_id": SALES, "columns": ["sku"],
                              "aggregations": [{"column": "qty", "fn": "SUM", "alias": "qty_sum"}],
                              "order_by": [{"column": "qty_sum", "direction": "desc"}], "limit": 10})
    assert plan.sql == ("SELECT `t`.`sku` AS `sku`, SUM(`t`.`qty`) AS `qty_sum` FROM `" + SALES + "` AS `t` "
                        "GROUP BY `t`.`sku` ORDER BY `qty_sum` DESC LIMIT 10")


def test_count_distinct():
    plan = build_query(None, {"table_id": SALES, "aggregations": [{"column": "customer_id", "fn": "count_distinct", "alias": "kh"}]})
    assert "COUNT(DISTINCT `t`.`customer_id`) AS `kh`" in plan.sql


def test_join():
    spec = {"table_id": SALES, "columns": ["sku", "inv.stock"],
            "joins": [{"table_id": INV, "as": "inv", "on": [{"left": "sku", "right": "sku"}, {"left": "wh", "right": "wh"}]}],
            "aggregations": [{"column": "qty", "fn": "SUM", "alias": "qty_sum"}],
            "order_by": [{"column": "inv.stock", "direction": "asc"}]}
    sql = build_query(None, spec).sql
    assert "LEFT JOIN `" + INV + "` AS `inv` ON `t`.`sku` = `inv`.`sku` AND `t`.`wh` = `inv`.`wh`" in sql
    assert "`inv`.`stock` AS `inv_stock`" in sql and "ORDER BY `inv_stock` ASC" in sql
    assert "GROUP BY `t`.`sku`, `inv`.`stock`" in sql


def test_join_rejects_bad_input():
    base = {"table_id": SALES, "columns": ["sku"]}
    bad_joins = [
        [{"table_id": INV, "as": "inv", "on": [{"left": "sku", "right": "khong_co"}]}],
        [{"table_id": INV, "as": "t", "on": [{"left": "sku", "right": "sku"}]}],
        [{"table_id": INV, "as": "inv", "type": "cross", "on": [{"left": "sku", "right": "sku"}]}],
        [{"table_id": INV, "as": "inv", "on": []}],
    ]
    for joins in bad_joins:
        _raises(InvalidQuerySpecError, lambda: build_query(None, {**base, "joins": joins}))
    _raises(InvalidQuerySpecError, lambda: build_query(None, {**base, "columns": ["inv.stock"]}))
    _raises(bq_meta.OutOfScopeError, lambda: build_query(None, {**base, "joins": [
        {"table_id": "surya-495408.12_data_agent_log.x", "as": "x", "on": [{"left": "sku", "right": "sku"}]}]}))


def test_param_filters():
    spec = {"table_id": SALES, "columns": ["sku"], "filters": [
        {"column": "order_date", "op": "gte", "type": "DATE", "param": "tu_ngay"},
        {"column": "wh", "op": "in", "type": "STRING", "param": "kho", "value": ["HN"]},
    ]}
    # Lúc validate upload (params=None): filter không có mặc định bị bỏ, filter có mặc định giữ.
    plan = build_query(None, spec)
    assert "`t`.`order_date`" not in plan.sql and "`t`.`wh` IN UNNEST(@embed_filter_1)" in plan.sql
    assert plan.query_parameters[0].values == ["HN"]

    plan = build_query(None, spec, {"tu_ngay": ["2026-10-01"], "kho": ["HN", "HCM"]})
    assert plan.query_parameters[0].value == datetime.date(2026, 10, 1)
    assert plan.query_parameters[1].values == ["HN", "HCM"]

    plan = build_query(None, spec, {"kho": [""]})  # rỗng = chủ động bỏ lọc, kể cả có mặc định
    assert "WHERE" not in plan.sql

    _raises(InvalidQuerySpecError, lambda: build_query(None, spec, {"tu_ngay": ["khong-phai-ngay"]}))
    _raises(InvalidQuerySpecError, lambda: build_query(None, {**spec, "filters": [
        {"column": "wh", "op": "eq", "type": "STRING", "param": "x; DROP"}]}))
    _raises(InvalidQuerySpecError, lambda: build_query(None, {**spec, "filters": [
        {"column": "wh", "op": "eq", "type": "STRING"}]}))
    assert declared_params({"specs": {"a": spec, "b": {"table_id": SALES}}}) == {"tu_ngay", "kho"}


def test_total_limit_cap():
    one = {"table_id": SALES, "columns": ["sku"], "limit": 60000}
    build_queries(None, {"specs": {"a": one}})
    _raises(InvalidQuerySpecError, lambda: build_queries(None, {"specs": {"a": one, "b": one}}))
    too_many = {f"s{i}": {"table_id": SALES, "columns": ["sku"]} for i in range(query_spec.Config.EMBED_DATA_MAX_SPECS + 1)}
    _raises(InvalidQuerySpecError, lambda: build_queries(None, {"specs": too_many}))


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
