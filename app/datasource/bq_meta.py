"""Đọc metadata bảng LIVE từ BigQuery INFORMATION_SCHEMA cho các dataset tầng
Serving (config.Config.SERVING_DATASETS) — thay cho catalog snapshot cũ. Cache
trong process với TTL, cùng pattern với app/catalog/client.py.

assert_in_scope() là hàng rào cứng: MỌI endpoint nhận table_id từ client (list
bảng, chi tiết bảng, preview) phải gọi hàm này trước khi chạm BigQuery — đúng
luật cứng #1 (chỉ dùng dữ liệu trong whitelist đã cấp quyền)."""

from __future__ import annotations

import re
import time
from typing import Any

from catalog.client import load_catalog
from config import Config
from google.cloud import bigquery

_cache: dict[str, Any] = {"tables": None, "loaded_at": 0.0}
_TTL_SECONDS = 600  # 10 phút — đủ mới, tránh quét INFORMATION_SCHEMA mỗi request

# Bắt "(9999 = không bán được, không tính)" trong Business Definition -> cảnh báo
# sentinel value cho preview, để user không tưởng nhầm 9999 là số liệu thật (đúng
# ca thật gặp: doh_avail=9999 nghĩa là "không tính", không phải 9999 ngày tồn kho).
_SENTINEL_RE = re.compile(r"\((\d+(?:\.\d+)?)\s*=\s*([^)]+)\)")


class OutOfScopeError(ValueError):
    """table_id không thuộc SERVING_DATASETS — không được đọc."""


def assert_in_scope(table_id: str) -> None:
    parts = table_id.split(".")
    if len(parts) != 3:
        raise OutOfScopeError(f"table_id không đúng dạng project.dataset.table: {table_id!r}")
    project, dataset, _ = parts
    if project != Config.GCP_PROJECT or dataset not in Config.SERVING_DATASETS:
        raise OutOfScopeError(
            f"'{table_id}' không thuộc phạm vi dữ liệu Serving đã cấp quyền."
        )


def _fetch_tables_for_dataset(client: bigquery.Client, dataset: str) -> list[dict[str, Any]]:
    project = Config.GCP_PROJECT
    # 1 câu gộp TABLES + TABLE_OPTIONS(description) bằng LEFT JOIN — mỗi dataset
    # 1 round-trip thay vì 2.
    sql = f"""
    SELECT
      t.table_name,
      t.table_type,
      o.option_value AS description
    FROM `{project}.{dataset}.INFORMATION_SCHEMA.TABLES` t
    LEFT JOIN `{project}.{dataset}.INFORMATION_SCHEMA.TABLE_OPTIONS` o
      ON t.table_name = o.table_name AND o.option_name = 'description'
    ORDER BY t.table_name
    """
    rows = list(client.query(sql).result())

    # __TABLES__ cho row_count/size/last_modified — VIEW không có dòng ở đây nên
    # trả 0/0/None cho view (frontend hiện "—" thay vì "0 dòng", xem app/web).
    stats_sql = f"SELECT table_id, row_count, size_bytes, last_modified_time FROM `{project}.{dataset}.__TABLES__`"
    stats_by_name = {r["table_id"]: r for r in client.query(stats_sql).result()}

    # Cột thật của MỌI bảng trong dataset, 1 query duy nhất (không WHERE table_name)
    # — bắt buộc phải có: nếu list_tables() không mang theo cột thật, prompt Advisor
    # (advisor/prompts.py) không có gì để trích, và LLM sẽ TỰ BỊA tên cột theo suy
    # đoán thay vì đọc từ dữ liệu thật — đúng lỗi đã bắt được khi test thủ công
    # (advisor trả "stock_composition", cột này không tồn tại). description ở đây
    # hầu như luôn rỗng trong project này (không ai set), nhưng vẫn lấy phòng khi có.
    cols_sql = f"""
    SELECT table_name, field_path, data_type, description
    FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`
    ORDER BY table_name, field_path
    """
    columns_by_table: dict[str, list[dict[str, str]]] = {}
    for r in client.query(cols_sql).result():
        columns_by_table.setdefault(r["table_name"], []).append(
            {"name": r["field_path"], "type": r["data_type"], "description": (r["description"] or "").strip()}
        )

    # Cột partition THẬT (is_partitioning_column) — dùng để preview ưu tiên dữ liệu
    # mới nhất (datasource/preview.py). VIEW không có dòng ở đây (không phải object
    # vật lý được partition) — preview.py fallback sang Lark 'partition' field.
    partition_sql = f"""
    SELECT table_name, column_name
    FROM `{project}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
    WHERE is_partitioning_column = 'YES'
    """
    partition_col_by_table = {r["table_name"]: r["column_name"] for r in client.query(partition_sql).result()}

    tables = []
    for r in rows:
        stats = stats_by_name.get(r["table_name"])
        # last_modified_time trong __TABLES__ là epoch millis (INTEGER), không phải
        # TIMESTAMP — tự quy đổi ở Python, không JOIN thêm 1 câu SQL nữa.
        last_modified_ms = stats["last_modified_time"] if stats else None
        tables.append({
            "table_id": f"{project}.{dataset}.{r['table_name']}",
            "project": project,
            "dataset": dataset,
            "table_name": r["table_name"],
            "table_type": r["table_type"],  # "BASE TABLE" | "VIEW"
            "description": (r["description"] or "").strip(),
            "row_count": stats["row_count"] if stats else None,
            "size_bytes": stats["size_bytes"] if stats else None,
            "columns": columns_by_table.get(r["table_name"], []),
            "partition_column": partition_col_by_table.get(r["table_name"]),
            "last_modified_at": (
                None if not last_modified_ms
                else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_modified_ms / 1000))
            ),
        })
    return tables


def _parse_sentinel_notes(description: str) -> list[dict[str, str]]:
    """Trích các cặp 'giá trị = ý nghĩa' viết trong ngoặc của Business Definition,
    vd '(9999 = không bán được, không tính)' -> [{"value": "9999", "meaning":
    "không bán được, không tính"}]. Rỗng nếu mô tả không theo mẫu này — KHÔNG suy
    diễn, chỉ trích đúng những gì đã viết tường minh."""
    return [
        {"value": m.group(1), "meaning": m.group(2).strip()}
        for m in _SENTINEL_RE.finditer(description or "")
    ]


def enrich_from_lark(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gắn thêm mô tả nghiệp vụ (Purpose/Grain/Refresh/PII Note/KPI liên quan) +
    mô tả CẤP CỘT (tên thân thiện/Business Definition/sentinel value từ '03.
    Column Dictionary') từ catalog Lark (catalog_sync) nếu đọc được. Lỗi (GCS
    down, catalog rỗng, bảng chưa có trong Lark...) KHÔNG được làm sập app — chỉ
    trả nguyên metadata BigQuery thuần, không có phần làm giàu."""
    try:
        catalog = load_catalog()
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO: không đọc được catalog Lark để làm giàu metadata bảng: {e}")
        return tables

    lark_by_table_id = {t["table_id"]: t for t in catalog.get("tables", [])}
    enriched = []
    for t in tables:
        has_lark = t["table_id"] in lark_by_table_id
        lark = lark_by_table_id.get(t["table_id"]) or {}
        merged = dict(t)
        merged["purpose"] = lark.get("purpose", "")
        merged["grain"] = lark.get("grain", "")
        merged["refresh"] = lark.get("refresh", "")
        merged["domain"] = lark.get("domain", "")
        pii_note = lark.get("pii_note", "")
        merged["pii_note"] = pii_note
        merged["has_pii"] = bool(pii_note) and pii_note.strip().lower() not in ("không", "no", "none", "")
        merged["kpi_names"] = lark.get("kpi_names", [])
        merged["has_lark_description"] = has_lark

        # Không có partition column thật từ BigQuery (thường là VIEW) -> thử dùng
        # field 'partition' của Lark, nhưng PHẢI validate khớp 1 cột thật của bảng
        # này — không tin chữ tự do trong Lark có thể lỗi thời/gõ sai.
        real_col_names = {c["name"] for c in merged.get("columns", [])}
        lark_partition = lark.get("partition", "").strip()
        if not merged.get("partition_column") and lark_partition in real_col_names:
            merged["partition_column"] = lark_partition

        # Mô tả cấp cột từ Column Dictionary, khớp theo tên cột trong CHÍNH bảng
        # Lark (không phải toàn catalog) — tránh khớp nhầm cột trùng tên ở bảng khác.
        # calculation_logic/example cũng có trong Column Dictionary nhưng chưa có
        # nơi nào đọc tới (không hiện ở API/UI) nên không thread qua đây — cần thì
        # thêm lại 2 dòng, dữ liệu gốc vẫn còn nguyên trong catalog Lark.
        lark_cols_by_name = {c["name"]: c for c in lark.get("columns", [])}
        new_columns = []
        for col in merged.get("columns", []):
            col = dict(col)
            lark_col = lark_cols_by_name.get(col["name"])
            col["friendly_name"] = lark_col.get("friendly_name", "") if lark_col else ""
            # Business Definition (nếu có) đáng tin hơn description rỗng của BigQuery.
            if lark_col and lark_col.get("description"):
                col["description"] = lark_col["description"]
            col["sentinel_values"] = _parse_sentinel_notes(col.get("description", ""))
            new_columns.append(col)
        merged["columns"] = new_columns

        enriched.append(merged)
    return enriched


def list_tables(client: bigquery.Client, force_reload: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force_reload and _cache["tables"] is not None and (now - _cache["loaded_at"]) < _TTL_SECONDS:
        return _cache["tables"]

    tables: list[dict[str, Any]] = []
    for dataset in Config.SERVING_DATASETS:
        tables.extend(_fetch_tables_for_dataset(client, dataset))
    tables = enrich_from_lark(tables)

    _cache["tables"] = tables
    _cache["loaded_at"] = now
    return tables


def get_table(client: bigquery.Client, table_id: str) -> dict[str, Any] | None:
    """Chi tiết 1 bảng — lấy thẳng từ list_tables() (đã có cache + cột đầy đủ kèm
    mô tả/tên thân thiện/sentinel value từ enrich_from_lark), không query thêm."""
    assert_in_scope(table_id)
    tables = list_tables(client)
    meta = next((t for t in tables if t["table_id"] == table_id), None)
    return dict(meta) if meta is not None else None
