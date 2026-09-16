"""Repository cho `raw_dashboard_builder_embeds` — tách riêng khỏi bq_store.py vì
module đó cam kết insert-only/không đọc (xem docstring bq_store.py). Embeds cần
đọc lại (list embed của tôi, tra cứu trạng thái hiện tại) nên có module riêng.

Trạng thái hiện tại của 1 embed = bản ghi MỚI NHẤT theo embed_id (event='created'
hay 'revoked'), lấy qua view raw_dashboard_builder_v_current_embeds (xem
app/storage/ddl/010_v_current_dashboard_embeds.sql) — không UPDATE trực tiếp,
"revoke" chỉ là ghi thêm 1 dòng event mới, đúng quy ước append-only của app."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery


def _table(name: str) -> str:
    project = os.environ["GCP_PROJECT"]
    dataset = os.environ["BQ_APP_DATASET"]
    prefix = os.environ.get("BQ_APP_TABLE_PREFIX", "raw_dashboard_builder_")
    return f"{project}.{dataset}.{prefix}{name}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_embed_event(
    client: bigquery.Client,
    embed_id: str,
    event: str,
    created_by: str,
    title: str | None = None,
    gcs_path: str | None = None,
    data_table_id: str | None = None,
    data_query_spec: dict[str, Any] | None = None,
) -> None:
    row = {
        "embed_id": embed_id,
        "event": event,
        "title": title,
        "created_by": created_by,
        "gcs_path": gcs_path,
        "data_table_id": data_table_id,
        "data_query_spec": json.dumps(data_query_spec, ensure_ascii=False) if data_query_spec else None,
        "event_at": _now(),
    }
    table_id = _table("embeds")
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Ghi {table_id} thất bại: {errors}")


def _row_to_dict(row: bigquery.table.Row) -> dict[str, Any]:
    d = dict(row.items())
    # BigQuery client tự parse cột JSON thành dict/list Python sẵn (không phải
    # string) — chỉ json.loads() nếu thực sự còn là string, tránh lỗi
    # "must be str, bytes or bytearray" khi client library đã tự deserialize.
    spec = d.get("data_query_spec")
    if isinstance(spec, str):
        d["data_query_spec"] = json.loads(spec)
    return d


def get_current_embed(client: bigquery.Client, embed_id: str) -> dict[str, Any] | None:
    sql = f"SELECT * FROM `{_table('v_current_embeds')}` WHERE embed_id = @embed_id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("embed_id", "STRING", embed_id)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    if not rows:
        return None
    return _row_to_dict(rows[0])


def list_current_embeds(client: bigquery.Client, created_by: str | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM `{_table('v_current_embeds')}` WHERE event != 'revoked'"
    query_parameters = []
    if created_by is not None:
        sql += " AND created_by = @created_by"
        query_parameters.append(bigquery.ScalarQueryParameter("created_by", "STRING", created_by))
    sql += " ORDER BY event_at DESC"
    job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
    rows = list(client.query(sql, job_config=job_config).result())
    return [_row_to_dict(r) for r in rows]
