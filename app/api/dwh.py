"""API phục vụ DWH Explorer — Knowledge Map (graph nodes + edges) và Data
Catalog (tìm kiếm bảng/cột/KPI).

Dữ liệu gốc hoàn toàn tái sử dụng từ bq_meta.list_tables() (đã có cache
TTL 10 phút) + catalog Lark (load_catalog), KHÔNG query thêm BigQuery.

3 route bên dưới khai báo `def` thường (KHÔNG `async def`): thân hàm chỉ
toàn lời gọi BigQuery/bq_store đồng bộ — đúng pattern catalog.py đã giải
thích kỹ (FastAPI tự đưa vào thread pool)."""

from __future__ import annotations

from typing import Any

from auth.deps import get_current_user
from catalog.client import load_catalog
from datasource import bq_meta
from fastapi import APIRouter, Depends
from google.cloud import bigquery

router = APIRouter(prefix="/api/dwh")

_client: bigquery.Client | None = None


def _get_bq_client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client()
    return _client


# ---------------------------------------------------------------------------
# Knowledge Map — build graph
# ---------------------------------------------------------------------------

import re

_UPSTREAM_RE = re.compile(
    r"((?:surya-495408\.)?(?:10_lsr|09_logic_serving|dim_dwh|12_data_agent_log|00_serving_[a-z0-9_]+)\.[a-zA-Z0-9_]+)"
)


def _extract_upstream_sources(t: dict[str, Any]) -> list[str]:
    """Trích danh sách các bảng nguồn upstream từ [Nguồn] và SQL view definition."""
    raw = f"{t.get('source_info', '')} {t.get('view_definition', '')}"
    sources = set()
    for m in _UPSTREAM_RE.findall(raw):
        clean = m.replace("surya-495408.", "").strip()
        if clean:
            sources.add(clean)
    return sorted(sources)


def _build_graph(
    tables: list[dict[str, Any]],
    kpis: list[dict[str, Any]],
) -> dict[str, Any]:
    """Dựng graph (nodes + edges) từ tables + KPIs cho Knowledge Map."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_datasets: set[str] = set()
    total_columns = 0
    domains: set[str] = set()

    valid_table_ids = {t["table_id"] for t in tables}
    table_id_by_short_name = {
        f"{t['dataset']}.{t['table_name']}": t["table_id"] for t in tables
    }

    # ---- Dataset + Table nodes ----
    for t in tables:
        ds = t["dataset"]
        total_columns += len(t.get("columns", []))
        domain = (t.get("domain") or "").strip()
        if domain:
            domains.add(domain)

        if ds not in seen_datasets:
            seen_datasets.add(ds)
            ds_tables = [x for x in tables if x["dataset"] == ds]
            nodes.append({
                "id": f"ds:{ds}",
                "type": "dataset",
                "label": ds,
                "group": ds,
                "metadata": {
                    "table_count": len(ds_tables),
                    "total_rows": sum(x.get("row_count") or 0 for x in ds_tables),
                },
            })

        upstream = _extract_upstream_sources(t)
        t["upstream_sources"] = upstream
        kpi_count = len(t.get("kpi_names") or [])

        nodes.append({
            "id": f"table:{t['table_id']}",
            "type": "table",
            "label": t["table_name"],
            "group": ds,
            "metadata": {
                "table_id": t["table_id"],
                "dataset": ds,
                "domain": domain,
                "purpose": t.get("purpose", ""),
                "grain": t.get("grain", ""),
                "refresh": t.get("refresh", ""),
                "row_count": t.get("row_count"),
                "columns_count": len(t.get("columns", [])),
                "has_pii": t.get("has_pii", False),
                "table_type": t.get("table_type", ""),
                "kpi_count": kpi_count,
                "partition_column": t.get("partition_column", ""),
                "cluster": t.get("cluster", ""),
                "keys_info": t.get("keys_info", ""),
                "source_info": t.get("source_info", ""),
                "transformation": t.get("transformation", ""),
                "scope": t.get("scope", ""),
                "use_when": t.get("use_when", ""),
                "not_use_when": t.get("not_use_when", ""),
                "notes": t.get("notes", ""),
                "upstream_sources": upstream,
                "has_view_sql": bool(t.get("view_definition")),
            },
        })

        # Dataset -> Table
        edges.append({
            "source": f"ds:{ds}",
            "target": f"table:{t['table_id']}",
            "type": "contains",
        })

        # Intra-serving table -> table (derives / lineage)
        for src in upstream:
            # src dạng '00_serving_sales.vw_xyz'
            src_full_id = table_id_by_short_name.get(src)
            if src_full_id and src_full_id != t["table_id"]:
                edges.append({
                    "source": f"table:{src_full_id}",
                    "target": f"table:{t['table_id']}",
                    "type": "derives",
                })

    # ---- KPI nodes ----
    seen_kpis: set[str] = set()
    for kpi in kpis:
        name = kpi.get("name", "")
        if not name or name in seen_kpis:
            continue
        seen_kpis.add(name)

        nodes.append({
            "id": f"kpi:{name}",
            "type": "kpi",
            "label": name,
            "group": "kpi",
            "metadata": {
                "formula": kpi.get("formula", ""),
                "business_definition": kpi.get("business_definition", ""),
                "domain": kpi.get("domain", ""),
                "status": kpi.get("status", ""),
                "grain": kpi.get("grain", ""),
                "owner": kpi.get("owner", ""),
                "time_rule": kpi.get("time_rule", ""),
                "kpi_type": kpi.get("type", ""),
            },
        })

        for table_id in kpi.get("tables", []):
            if table_id in valid_table_ids:
                edges.append({
                    "source": f"table:{table_id}",
                    "target": f"kpi:{name}",
                    "type": "feeds",
                })

    stats = {
        "total_tables": len(tables),
        "total_columns": total_columns,
        "total_kpis": len(seen_kpis),
        "total_datasets": len(seen_datasets),
        "domains": sorted(domains),
    }
    return {"nodes": nodes, "edges": edges, "stats": stats}


# ---------------------------------------------------------------------------
# Data Catalog — related tables (shared columns)
# ---------------------------------------------------------------------------

def _find_related_tables(tables: list[dict[str, Any]]) -> None:
    """Tìm bảng liên quan dựa trên cột trùng tên (≥ 3 cột chung → có khả
    năng JOIN được). O(n²) nhưng n ≤ 50 nên tức thì. Gắn in-place."""
    cols_index = [
        {c["name"] for c in t.get("columns", [])} for t in tables
    ]
    for i, t1 in enumerate(tables):
        related = []
        for j, t2 in enumerate(tables):
            if i == j:
                continue
            shared = cols_index[i] & cols_index[j]
            if len(shared) >= 3:
                related.append({
                    "table_id": t2["table_id"],
                    "table_name": t2["table_name"],
                    "dataset": t2["dataset"],
                    "shared_columns": sorted(shared),
                    "shared_count": len(shared),
                })
        t1["related_tables"] = sorted(related, key=lambda x: -x["shared_count"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/graph")
def get_graph(user: str = Depends(get_current_user)):
    """Knowledge Map: nodes + edges + stats."""
    client = _get_bq_client()
    tables = bq_meta.list_tables(client)

    kpis: list[dict[str, Any]] = []
    try:
        catalog = load_catalog()
        kpis = catalog.get("kpis", [])
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO: không đọc được KPI từ catalog Lark cho Knowledge Map: {e}")

    return _build_graph(tables, kpis)


@router.get("/catalog")
def get_catalog(user: str = Depends(get_current_user)):
    """Data Catalog: bảng (kèm related_tables và upstream_sources) + KPIs cho tìm kiếm."""
    client = _get_bq_client()
    tables = bq_meta.list_tables(client)
    for t in tables:
        t["upstream_sources"] = _extract_upstream_sources(t)
    _find_related_tables(tables)

    kpis: list[dict[str, Any]] = []
    try:
        catalog = load_catalog()
        kpis = catalog.get("kpis", [])
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO: không đọc được KPI từ catalog Lark cho Data Catalog: {e}")

    return {"tables": tables, "kpis": kpis}
