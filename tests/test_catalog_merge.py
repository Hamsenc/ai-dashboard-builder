"""Test merge.py bằng fixture lấy từ dữ liệu THẬT đã đọc trực tiếp từ Lark Base
(AcITbzsvraObhisDdQXlO6tggkd, bảng '02. Table Catalog' + '04. Business Logic - KPI')
trong lúc khảo sát ban đầu — record_id, Table_ID, Status, công thức... đều là giá trị
thật, không bịa. Riêng ĐỊNH DẠNG bọc ngoài {record_id, fields} là định dạng chuẩn của
Lark Bitable REST API (lark_client.list_records trả về), không phải định dạng cột-mảng
riêng của MCP tool dùng lúc khảo sát.

info_schema dùng thật information_schema.fetch_columns() gọi BigQuery thật — test này
CẦN mạng + quyền BigQuery (giống các test khác trong dự án dùng dữ liệu thật thay vì mock).
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "catalog_sync"))

from google.cloud import bigquery

from information_schema import fetch_columns
from merge import build_catalog

# 5 dòng thật từ '02. Table Catalog', Layer=Serving, domain Sales (record_id thật).
TABLE_CATALOG_RECORDS = [
    {
        "record_id": "recvsZU53SRano",
        "fields": {
            "Table_ID": ["surya-495408.00_serving_sales.vw_business_daily"],
            "Status": ["Active"],
            "Purpose": "P&L tổng hợp all-channel theo ngày",
            "Partition": "date",
            "PII Note": "Không",
            "Cluster": "brand_id, warehouse_key, channel_key",
            "Layer": ["Serving"],
            "Refresh": "Hourly (24x/ngày)",
            "Grain": "1 dòng = 1 ngày × brand_id × channel_key × warehouse_key",
            "Domain": ["Sales"],
            "Dataset": ["00_serving_sales"],
        },
    },
    {
        "record_id": "recvsZU53SIEXj",
        "fields": {
            "Table_ID": ["surya-495408.00_serving_sales.vw_business_daily_retail"],
            "Status": ["Active"],
            "Purpose": "P&L retail theo cửa hàng",
            "Partition": "date",
            "PII Note": "Không",
            "Cluster": "brand_id, warehouse_key",
            "Layer": ["Serving"],
            "Refresh": "Hourly (24x/ngày)",
            "Grain": "1 dòng = 1 ngày × brand_id × channel_key × warehouse_key (retail only)",
            "Domain": ["Sales"],
            "Dataset": ["00_serving_sales"],
        },
    },
    {
        "record_id": "recvsZU53SAhvD",
        "fields": {
            "Table_ID": ["surya-495408.00_serving_sales.vw_sales_daily_product"],
            "Status": ["Active"],
            "Purpose": "Doanh số theo SKU/category/salesperson",
            "Partition": "date",
            "PII Note": "Có (salesperson_key/marketingpic_key = định danh nhân viên nội bộ)",
            "Cluster": "brand_id, channel_name, warehouse_key, sku",
            "Layer": ["Serving"],
            "Refresh": "Hourly (24x/ngày)",
            "Grain": "1 dòng = 1 ngày × brand × channel × warehouse × salesperson × marketingpic × koc_affiliate × sku",
            "Domain": ["Sales"],
            "Dataset": ["00_serving_sales"],
        },
    },
    {
        "record_id": "recvsZU53SlPBX",
        "fields": {
            "Table_ID": ["surya-495408.00_serving_sales.vw_sales_hourly"],
            "Status": ["Active"],
            "Purpose": "Hiệu suất bán + chi phí theo giờ (CIR/BLG/LNDG)",
            "Partition": "created_date",
            "PII Note": "Không",
            "Cluster": "created_hour, brand_id, channel",
            "Layer": ["Serving"],
            "Refresh": "Hourly (24x/ngày)",
            "Grain": "1 dòng = 1 giờ × ngày × brand_id × channel",
            "Domain": ["Sales"],
            "Dataset": ["00_serving_sales"],
        },
    },
    {
        "record_id": "recvsZU53S9Sib",
        "fields": {
            "Table_ID": ["surya-495408.00_serving_sales.vw_sales_order"],
            "Status": ["Active"],
            "Purpose": "Chi tiết đơn hàng (audit/join)",
            "Partition": "created_date",
            "PII Note": "Không",
            "Cluster": "order_id, brand_id",
            "Layer": ["Serving"],
            "Refresh": "Hourly (24x/ngày)",
            "Grain": "1 dòng = 1 order_id × brand_id",
            "Domain": ["Sales"],
            "Dataset": ["00_serving_sales"],
        },
    },
]

# Dòng KPI thật từ '04. Business Logic - KPI'. Link Table_ID của "GMV (Created)" trong
# Lark thật có 8 record_id (nhiều hơn 5 record ở trên vì còn trỏ tới bảng ở layer khác
# như 09_logic_serving/00_report) — giữ nguyên để test đúng hành vi "khớp 1 phần":
# chỉ 4/8 record_id khớp whitelist Serving, KPI vẫn phải vào in-scope vì có ít nhất 1 khớp.
KPI_RECORDS = [
    {
        "record_id": "recvtonUbofYib",
        "fields": {
            "Name": "GMV (Created)",
            "Table_ID": [
                {"id": "recvsZU53S9Sib"}, {"id": "recvsZU53SAhvD"},
                {"id": "recvsZU53SIEXj"}, {"id": "recvsZU53SRano"},
                {"id": "recvt184X934Kf"}, {"id": "recvt184X9PYl2"},
                {"id": "recvt184X9ZLQP"}, {"id": "recvt184X9ypNx"},
            ],
            "Formula / Rule": (
                "SUM(gmv_created) theo brand × channel × ngày, không filter order_status.\n"
                "⚠️ Công thức SQL gốc chưa được ghi lại trong Column Dictionary — cần xác "
                "nhận với chủ sở hữu pipeline 09_logic_serving trước khi chuyển Status sang Active."
            ),
            "Domain": ["Sales"],
            "Business Definition": (
                "Tổng giá trị đơn hàng (GMV) tính trên TẤT CẢ đơn được tạo trong kỳ, không "
                "lọc theo trạng thái đơn."
            ),
            "Grain": "1 dòng = ngày × brand_id × channel_key × warehouse_key",
            "Status": "Draft",
            "Owner": "BI Team",
            "Time Rule": "⚠️ Chưa xác nhận mốc thời gian chuẩn hoá giữa các bảng.",
            "Type": "Metric (base)",
            "Version": "1.0",
            "Input Tables / Columns": "gmv_created (00_serving_sales / 00_report / 09_logic_serving / ...)",
        },
    },
    {
        "record_id": "recvtoIWrDEBGL",
        "fields": {
            "Name": "Customer Recency (số ngày từ lần mua gần nhất)",
            "Table_ID": [],
            "Formula / Rule": "recency_days ≈ ngày hiện tại − most_recent_order_date, theo customer_key × brand.",
            "Domain": ["Customer"],
            "Business Definition": "Số ngày từ lần mua hàng gần nhất tới thời điểm tính.",
            "Grain": "1 dòng = 1 customer_key × brand",
            "Status": "Draft",
            "Owner": "BI Team",
            "Time Rule": "",
            "Type": "Metric (base)",
            "Version": "1.0",
            "Input Tables / Columns": "recency_days (vw_customer_brand)",
        },
    },
    {
        "record_id": "recvtpXnBpxDxt",
        "fields": {
            "Name": "Ad Spend",
            "Table_ID": [{"id": "recvt184X98NT4"}],
            "Formula / Rule": "SUM(spend) theo campaign_id × account_id × platform × date_start.",
            "Domain": ["Marketing"],
            "Business Definition": "Tổng chi phí quảng cáo.",
            "Grain": "1 dòng = 1 campaign_id × account_id × platform × date_start",
            "Status": "Draft",
            "Owner": "BI Team",
            "Time Rule": "",
            "Type": "Metric (base)",
            "Version": "1.0",
            "Input Tables / Columns": "spend (10_lsr.fact_ads_performance)",
        },
    },
]


def test_build_catalog_with_real_data():
    client = bigquery.Client(project="surya-495408")
    info_schema = fetch_columns(
        client,
        "surya-495408",
        {
            "00_serving_sales": [
                "vw_business_daily",
                "vw_business_daily_retail",
                "vw_sales_daily_product",
                "vw_sales_hourly",
                "vw_sales_order",
            ]
        },
    )

    catalog = build_catalog(
        TABLE_CATALOG_RECORDS, KPI_RECORDS, info_schema, generated_at="2026-09-03T00:00:00Z"
    )

    assert len(catalog["tables"]) == 5, catalog["tables"]
    for t in catalog["tables"]:
        assert len(t["columns"]) > 0, f"bảng {t['table_id']} phải có cột thật từ BigQuery"
        assert "record_id" not in t, "record_id là chi tiết nội bộ Lark, không lộ ra catalog"

    kpi_names = {k["name"] for k in catalog["kpis"]}
    assert "GMV (Created)" in kpi_names
    gmv = next(k for k in catalog["kpis"] if k["name"] == "GMV (Created)")
    assert gmv["status"] == "Draft"
    assert set(gmv["tables"]) == {
        "surya-495408.00_serving_sales.vw_sales_order",
        "surya-495408.00_serving_sales.vw_sales_daily_product",
        "surya-495408.00_serving_sales.vw_business_daily_retail",
        "surya-495408.00_serving_sales.vw_business_daily",
    }, "chỉ 4/8 record_id link khớp whitelist Serving -> KPI vẫn in-scope vì có >=1 khớp"

    out_of_scope_names = {k["name"] for k in catalog["out_of_scope_kpis"]}
    assert "Customer Recency (số ngày từ lần mua gần nhất)" in out_of_scope_names
    assert "Ad Spend" in out_of_scope_names
    for k in catalog["out_of_scope_kpis"]:
        assert k["reason"], f"KPI ngoài phạm vi phải có lý do rõ ràng: {k['name']}"

    vw_business_daily = next(
        t for t in catalog["tables"]
        if t["table_id"] == "surya-495408.00_serving_sales.vw_business_daily"
    )
    assert "GMV (Created)" in vw_business_daily["kpi_names"]

    print("OK — tất cả assertion pass")


if __name__ == "__main__":
    test_build_catalog_with_real_data()
