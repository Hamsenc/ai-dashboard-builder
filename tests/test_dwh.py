"""Test module dwh.py (API Knowledge Map & Data Catalog cho DWH Explorer)."""

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from api.dwh import _build_graph, _extract_upstream_sources, _find_related_tables


def test_extract_upstream_sources():
    table = {
        "source_info": "Materialize từ 09_logic_serving.sales_sql_vw_business_daily (base_fact_sales_order_detail_sales, 10_lsr.fact_order_transaction, dim_dwh.dim_brand)",
        "view_definition": "SELECT * FROM `surya-495408.00_serving_inventory.vw_inventory_position` JOIN `dim_dwh.dim_product` USING(sku)",
    }
    sources = _extract_upstream_sources(table)
    assert "09_logic_serving.sales_sql_vw_business_daily" in sources
    assert "10_lsr.fact_order_transaction" in sources
    assert "dim_dwh.dim_brand" in sources
    assert "00_serving_inventory.vw_inventory_position" in sources
    assert "dim_dwh.dim_product" in sources


def test_build_graph_structure_and_lineage():
    tables = [
        {
            "table_id": "surya-495408.00_serving_sales.vw_sales_daily_product",
            "table_name": "vw_sales_daily_product",
            "dataset": "00_serving_sales",
            "domain": "Sales",
            "table_type": "BASE TABLE",
            "purpose": "Doanh số theo SKU",
            "grain": "1 dòng = date × sku",
            "partition_column": "date",
            "cluster": "brand_id, sku",
            "keys_info": "PK: date, sku",
            "source_info": "Materialize từ 09_logic_serving.sales_sql_vw_sales_daily_product",
            "transformation": "SKU quy về gốc",
            "columns": [
                {"name": "date", "type": "DATE"},
                {"name": "sku", "type": "STRING"},
                {"name": "revenue", "type": "FLOAT64"},
            ],
            "row_count": 1000,
            "has_pii": False,
            "kpi_names": ["GMV"],
        },
        {
            "table_id": "surya-495408.00_serving_sales.vw_sales_daily_product_inventory",
            "table_name": "vw_sales_daily_product_inventory",
            "dataset": "00_serving_sales",
            "domain": "Sales",
            "table_type": "BASE TABLE",
            "purpose": "Doanh số kèm tồn",
            "source_info": "Materialize từ 09_logic_serving.x (00_serving_sales.vw_sales_daily_product)",
            "columns": [{"name": "date", "type": "DATE"}],
            "row_count": 500,
            "kpi_names": [],
        },
    ]

    kpis = [
        {
            "name": "GMV",
            "tables": ["surya-495408.00_serving_sales.vw_sales_daily_product", "non_existent_table"],
            "formula": "SUM(revenue)",
            "status": "Active",
            "domain": "Sales",
        }
    ]

    graph = _build_graph(tables, kpis)
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = graph["edges"]

    # Datasets, tables, KPIs
    assert "ds:00_serving_sales" in nodes
    assert "table:surya-495408.00_serving_sales.vw_sales_daily_product" in nodes
    assert "kpi:GMV" in nodes

    # Edge: dataset contains table
    contains_edges = [e for e in edges if e["type"] == "contains"]
    assert any(
        e["source"] == "ds:00_serving_sales"
        and e["target"] == "table:surya-495408.00_serving_sales.vw_sales_daily_product"
        for e in contains_edges
    )

    # Edge: table feeds KPI (and skips non_existent_table)
    feeds_edges = [e for e in edges if e["type"] == "feeds"]
    assert len(feeds_edges) == 1
    assert feeds_edges[0]["source"] == "table:surya-495408.00_serving_sales.vw_sales_daily_product"
    assert feeds_edges[0]["target"] == "kpi:GMV"

    # Edge: derives (intra-serving lineage between tables)
    derives_edges = [e for e in edges if e["type"] == "derives"]
    assert len(derives_edges) == 1
    assert derives_edges[0]["source"] == "table:surya-495408.00_serving_sales.vw_sales_daily_product"
    assert derives_edges[0]["target"] == "table:surya-495408.00_serving_sales.vw_sales_daily_product_inventory"

    # Stats
    assert graph["stats"]["total_tables"] == 2
    assert graph["stats"]["total_kpis"] == 1
    assert graph["stats"]["total_datasets"] == 1
    assert "Sales" in graph["stats"]["domains"]


def test_find_related_tables():
    tables = [
        {
            "table_id": "t1",
            "table_name": "table_1",
            "dataset": "ds1",
            "columns": [{"name": "col_a"}, {"name": "col_b"}, {"name": "col_c"}, {"name": "col_d"}],
        },
        {
            "table_id": "t2",
            "table_name": "table_2",
            "dataset": "ds1",
            "columns": [{"name": "col_a"}, {"name": "col_b"}, {"name": "col_c"}, {"name": "col_x"}],
        },
        {
            "table_id": "t3",
            "table_name": "table_3",
            "dataset": "ds2",
            "columns": [{"name": "col_a"}, {"name": "col_y"}],  # chỉ trùng 1 cột -> không đủ >= 3
        },
    ]

    _find_related_tables(tables)

    # t1 và t2 có 3 cột chung (col_a, col_b, col_c)
    assert len(tables[0]["related_tables"]) == 1
    assert tables[0]["related_tables"][0]["table_id"] == "t2"
    assert tables[0]["related_tables"][0]["shared_count"] == 3
    assert tables[0]["related_tables"][0]["shared_columns"] == ["col_a", "col_b", "col_c"]

    # t3 không có bảng nào trùng >= 3 cột
    assert len(tables[2]["related_tables"]) == 0


def test_dwh_endpoints(monkeypatch):
    import os
    from fastapi.testclient import TestClient
    from main import app
    from unittest.mock import patch

    monkeypatch.setenv("ALLOW_DEV_USER_HEADER", "true")
    client = TestClient(app)

    # 1. dwh.html serves 200
    r_html = client.get("/dwh.html")
    assert r_html.status_code == 200
    assert "DWH Explorer" in r_html.text

    # 2. /api/dwh/graph and /api/dwh/catalog
    mock_tables = [
        {
            "table_id": "surya-495408.00_serving_sales.vw_sales",
            "table_name": "vw_sales",
            "dataset": "00_serving_sales",
            "columns": [{"name": "id", "type": "INT64"}],
            "domain": "Sales",
            "purpose": "Doanh số",
            "kpi_names": ["GMV"],
        }
    ]
    mock_kpis = [{"name": "GMV", "tables": ["surya-495408.00_serving_sales.vw_sales"]}]

    with patch("api.dwh.bq_meta.list_tables", return_value=mock_tables), patch(
        "api.dwh.load_catalog", return_value={"kpis": mock_kpis}
    ):
        r_graph = client.get("/api/dwh/graph", headers={"X-Dev-User": "test@example.com"})
        assert r_graph.status_code == 200
        g = r_graph.json()
        assert len(g["nodes"]) == 3
        assert len(g["edges"]) == 2

        r_cat = client.get("/api/dwh/catalog", headers={"X-Dev-User": "test@example.com"})
        assert r_cat.status_code == 200
        c = r_cat.json()
        assert len(c["tables"]) == 1
        assert len(c["kpis"]) == 1
