"""Test validator.py — nhóm test giá trị cao nhất trong repo vì đây là ranh giới an
toàn thật sự (không phải sự tự giác của LLM). Test cả case hợp lệ lẫn các cách lách
whitelist/chèn statement lạ."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from builder.validator import validate_sql

WHITELIST = [
    "surya-495408.00_serving_sales.vw_business_daily",
    "surya-495408.00_serving_sales.vw_sales_order",
    "surya-495408.00_serving_inventory.vw_inventory_position",
]


def test_valid_select_passes():
    r = validate_sql(
        "SELECT date, brand_id, gmv_success FROM `surya-495408.00_serving_sales.vw_business_daily` WHERE date >= '2026-01-01'",
        WHITELIST,
    )
    assert r.passed, r.errors
    assert r.tables_touched == ["surya-495408.00_serving_sales.vw_business_daily"]


def test_table_outside_whitelist_rejected():
    r = validate_sql(
        "SELECT * FROM `surya-495408.00_serving_operation.vw_data_dashboard_quality_daily`",
        WHITELIST,
    )
    assert not r.passed
    assert any("không nằm trong whitelist" in e for e in r.errors)


def test_bare_table_name_rejected():
    r = validate_sql("SELECT * FROM vw_business_daily", WHITELIST)
    assert not r.passed
    assert any("fully-qualified" in e for e in r.errors)


def test_project_dataset_only_no_project_rejected():
    r = validate_sql("SELECT * FROM `00_serving_sales.vw_business_daily`", WHITELIST)
    assert not r.passed
    assert any("fully-qualified" in e for e in r.errors)


def test_multi_statement_rejected():
    sql = (
        "SELECT * FROM `surya-495408.00_serving_sales.vw_business_daily`; "
        "DROP TABLE `surya-495408.00_serving_sales.vw_business_daily`"
    )
    r = validate_sql(sql, WHITELIST)
    assert not r.passed
    assert any("multi-statement" in e for e in r.errors)


def test_drop_table_rejected():
    r = validate_sql("DROP TABLE `surya-495408.00_serving_sales.vw_business_daily`", WHITELIST)
    assert not r.passed


def test_insert_rejected():
    r = validate_sql(
        "INSERT INTO `surya-495408.00_serving_sales.vw_business_daily` VALUES (1)",
        WHITELIST,
    )
    assert not r.passed


def test_delete_rejected():
    r = validate_sql(
        "DELETE FROM `surya-495408.00_serving_sales.vw_business_daily` WHERE TRUE",
        WHITELIST,
    )
    assert not r.passed


def test_update_rejected():
    r = validate_sql(
        "UPDATE `surya-495408.00_serving_sales.vw_business_daily` SET gmv_success = 0 WHERE TRUE",
        WHITELIST,
    )
    assert not r.passed


def test_insert_select_smuggled_as_dml_rejected():
    """SELECT hợp lệ về mặt cấu trúc con nhưng bọc trong INSERT ... SELECT — vẫn phải chặn
    vì root/DML node là INSERT, không phải bản thân subquery SELECT."""
    sql = (
        "INSERT INTO `surya-495408.00_serving_sales.vw_business_daily` "
        "SELECT * FROM `surya-495408.00_serving_sales.vw_business_daily`"
    )
    r = validate_sql(sql, WHITELIST)
    assert not r.passed


def test_union_of_whitelisted_tables_passes():
    sql = (
        "SELECT brand_id FROM `surya-495408.00_serving_sales.vw_business_daily` "
        "UNION ALL "
        "SELECT brand_id FROM `surya-495408.00_serving_sales.vw_sales_order`"
    )
    r = validate_sql(sql, WHITELIST)
    assert r.passed, r.errors
    assert set(r.tables_touched) == {
        "surya-495408.00_serving_sales.vw_business_daily",
        "surya-495408.00_serving_sales.vw_sales_order",
    }


def test_union_with_one_disallowed_table_rejected():
    sql = (
        "SELECT brand_id FROM `surya-495408.00_serving_sales.vw_business_daily` "
        "UNION ALL "
        "SELECT dashboard FROM `surya-495408.00_serving_operation.vw_data_dashboard_quality_daily`"
    )
    r = validate_sql(sql, WHITELIST)
    assert not r.passed


def test_cte_using_only_whitelisted_tables_passes():
    """CTE (WITH ... AS (...)) là construct hợp lệ, phổ biến khi Builder gộp nhiều KPI —
    tên CTE khi được FROM tới không có catalog/db, KHÔNG được bị coi là lỗi 'chưa fully-qualified'."""
    sql = """
    WITH daily AS (
      SELECT date, brand_id, gmv_success
      FROM `surya-495408.00_serving_sales.vw_business_daily`
    )
    SELECT date, SUM(gmv_success) AS total_gmv
    FROM daily
    GROUP BY date
    """
    r = validate_sql(sql, WHITELIST)
    assert r.passed, r.errors
    assert r.tables_touched == ["surya-495408.00_serving_sales.vw_business_daily"]


def test_cte_referencing_disallowed_table_still_rejected():
    sql = """
    WITH bad AS (
      SELECT * FROM `surya-495408.00_serving_operation.vw_data_dashboard_quality_daily`
    )
    SELECT * FROM bad
    """
    r = validate_sql(sql, WHITELIST)
    assert not r.passed
    assert any("không nằm trong whitelist" in e for e in r.errors)


def test_unparseable_sql_rejected():
    r = validate_sql("SELEKT * FRM nowhere;;; garbage((", WHITELIST)
    assert not r.passed


def test_missing_backtick_around_table_rejected():
    """Bug thật đã gặp: sqlglot parse được table ref dù thiếu backtick (dễ tính hơn
    ngữ pháp BigQuery thật), nhưng BigQuery thật từ chối vì dataset bắt đầu bằng số
    (00_serving_sales) là identifier không hợp lệ nếu không backtick-quote. Phải bắt
    ở validator (retry được) thay vì để BigQuery từ chối lúc thực thi (tốn 1 build)."""
    r = validate_sql(
        "SELECT date FROM surya-495408.00_serving_sales.vw_business_daily WHERE date > '2026-01-01'",
        WHITELIST,
    )
    assert not r.passed
    assert any("backtick" in e for e in r.errors)


def test_partial_backtick_around_table_rejected():
    """Biến thể khác của cùng lỗi: backtick chỉ bọc project.dataset, không bọc cả
    table — đúng bug thật Builder tạo ra trong 1 nhánh UNION ALL."""
    r = validate_sql(
        "SELECT date FROM `surya-495408.00_serving_sales`.vw_business_daily WHERE date > '2026-01-01'",
        WHITELIST,
    )
    assert not r.passed
    assert any("backtick" in e for e in r.errors)


def test_select_star_produces_warning_not_error():
    r = validate_sql(
        "SELECT * FROM `surya-495408.00_serving_sales.vw_business_daily`",
        WHITELIST,
    )
    assert r.passed
    assert any("SELECT *" in w for w in r.warnings)


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if failed:
        raise SystemExit(1)
