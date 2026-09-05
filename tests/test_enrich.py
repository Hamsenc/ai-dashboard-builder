"""Test enrich_from_lark() trong datasource/bq_meta.py — khớp bảng BigQuery với
mô tả nghiệp vụ từ catalog Lark theo table_id, và PHẢI không ném exception khi đọc
catalog Lark lỗi (catalog_sync giờ chỉ là làm giàu tuỳ chọn, không phải nguồn bắt
buộc — xem README/app/main.py). Không cần credentials/network: monkeypatch thẳng
`load_catalog` trong namespace module thay vì gọi GCS thật (repo không có framework
mock nào sẵn, làm theo cách đơn giản nhất khớp style test hiện tại)."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

import datasource.bq_meta as bq_meta

RAW_TABLES = [
    {"table_id": "surya-495408.00_serving_sales.vw_business_daily", "table_name": "vw_business_daily"},
    {"table_id": "surya-495408.00_serving_sales.vw_sales_order", "table_name": "vw_sales_order"},
]


def test_enrich_matches_by_table_id():
    bq_meta.load_catalog = lambda: {
        "tables": [
            {
                "table_id": "surya-495408.00_serving_sales.vw_business_daily",
                "purpose": "P&L tổng hợp all-channel theo ngày",
                "grain": "1 dòng = 1 ngày",
                "refresh": "Hourly",
                "domain": "Sales",
                "pii_note": "Không",
                "kpi_names": ["GMV (Created)"],
            }
        ]
    }
    enriched = bq_meta.enrich_from_lark(RAW_TABLES)
    matched = next(t for t in enriched if t["table_id"] == "surya-495408.00_serving_sales.vw_business_daily")
    assert matched["purpose"] == "P&L tổng hợp all-channel theo ngày"
    assert matched["kpi_names"] == ["GMV (Created)"]
    assert matched["has_pii"] is False
    assert matched["has_lark_description"] is True


def test_enrich_unmatched_table_gets_empty_placeholders():
    bq_meta.load_catalog = lambda: {"tables": []}
    enriched = bq_meta.enrich_from_lark(RAW_TABLES)
    for t in enriched:
        assert t["purpose"] == ""
        assert t["kpi_names"] == []
        assert t["has_pii"] is False
        assert t["has_lark_description"] is False


def test_enrich_detects_pii_note():
    bq_meta.load_catalog = lambda: {
        "tables": [{"table_id": "surya-495408.00_serving_sales.vw_sales_order", "pii_note": "Có SĐT khách hàng"}]
    }
    enriched = bq_meta.enrich_from_lark(RAW_TABLES)
    matched = next(t for t in enriched if t["table_id"] == "surya-495408.00_serving_sales.vw_sales_order")
    assert matched["has_pii"] is True
    assert matched["pii_note"] == "Có SĐT khách hàng"


def test_enrich_merges_column_dictionary_and_parses_sentinel():
    tables_with_columns = [
        {
            "table_id": "surya-495408.00_serving_inventory.vw_inventory_position",
            "table_name": "vw_inventory_position",
            "columns": [
                {"name": "date", "type": "DATE", "description": ""},
                {"name": "doh_avail", "type": "FLOAT64", "description": ""},
            ],
        }
    ]
    bq_meta.load_catalog = lambda: {
        "tables": [
            {
                "table_id": "surya-495408.00_serving_inventory.vw_inventory_position",
                "columns": [
                    {
                        "name": "doh_avail",
                        "friendly_name": "Số ngày tồn kho khả dụng (DOH)",
                        "description": "Số ngày tồn khả dụng (9999 = không bán được, không tính).",
                    }
                ],
            }
        ]
    }
    enriched = bq_meta.enrich_from_lark(tables_with_columns)
    cols = {c["name"]: c for c in enriched[0]["columns"]}

    assert cols["doh_avail"]["friendly_name"] == "Số ngày tồn kho khả dụng (DOH)"
    assert cols["doh_avail"]["sentinel_values"] == [{"value": "9999", "meaning": "không bán được, không tính"}]
    # "date" không có trong Column Dictionary fixture -> vẫn còn trong output, chỉ
    # không có tên thân thiện/sentinel, KHÔNG bị rớt khỏi danh sách cột.
    assert cols["date"]["friendly_name"] == ""
    assert cols["date"]["sentinel_values"] == []


def test_enrich_partition_column_fallback_validated_against_real_columns():
    base_table = {
        "table_id": "surya-495408.00_serving_sales.vw_x",
        "table_name": "vw_x",
        "columns": [{"name": "date", "type": "DATE", "description": ""}],
        # partition_column KHÔNG có (giả lập VIEW không tự khai báo partition thật)
    }

    # Case 1: Lark khai partition="date", "date" CÓ thật trong cột -> được tin dùng.
    bq_meta.load_catalog = lambda: {
        "tables": [{"table_id": "surya-495408.00_serving_sales.vw_x", "partition": "date"}]
    }
    enriched = bq_meta.enrich_from_lark([base_table])
    assert enriched[0]["partition_column"] == "date"

    # Case 2: Lark khai partition="cot_khong_ton_tai" -> KHÔNG khớp cột thật nào,
    # không được tin dùng (tránh ORDER BY vào cột không tồn tại lúc preview).
    bq_meta.load_catalog = lambda: {
        "tables": [{"table_id": "surya-495408.00_serving_sales.vw_x", "partition": "cot_khong_ton_tai"}]
    }
    enriched = bq_meta.enrich_from_lark([base_table])
    assert not enriched[0].get("partition_column")


def test_enrich_catalog_error_returns_original_list_unchanged():
    def _raise():
        raise RuntimeError("GCS down")

    bq_meta.load_catalog = _raise
    result = bq_meta.enrich_from_lark(RAW_TABLES)
    assert result == RAW_TABLES  # nguyên vẹn, không thêm field, không ném exception


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
