"""Repository cho `raw_dashboard_builder_embeds` — tách riêng khỏi bq_store.py vì
module đó cam kết insert-only/không đọc (xem docstring bq_store.py). Embeds cần
đọc lại (list embed của tôi, tra cứu trạng thái hiện tại) nên có module riêng.

Trạng thái hiện tại của 1 embed = bản ghi MỚI NHẤT theo embed_id (event='created'
hay 'revoked'), lấy qua view raw_dashboard_builder_v_current_embeds (xem
app/storage/ddl/010_v_current_dashboard_embeds.sql) — không UPDATE trực tiếp,
"revoke" chỉ là ghi thêm 1 dòng event mới, đúng quy ước append-only của app."""

from __future__ import annotations

import json
from typing import Any

from google.cloud import bigquery
from storage._common import now as _now
from storage._common import table as _table


def insert_embed_event(
    client: bigquery.Client,
    embed_id: str,
    event: str,
    created_by: str,
    title: str | None = None,
    gcs_path: str | None = None,
    data_table_id: str | None = None,
    data_query_spec: dict[str, Any] | None = None,
    owner_name: str | None = None,
    prompt_note: str | None = None,
    data_file_gcs_path: str | None = None,
    data_file_name: str | None = None,
    group_name: str | None = None,
    data_file_columns: list[str] | None = None,
) -> None:
    row = {
        "embed_id": embed_id,
        "event": event,
        "title": title,
        "created_by": created_by,
        "gcs_path": gcs_path,
        "data_table_id": data_table_id,
        "data_query_spec": json.dumps(data_query_spec, ensure_ascii=False) if data_query_spec else None,
        "owner_name": owner_name,
        "prompt_note": prompt_note,
        "data_file_gcs_path": data_file_gcs_path,
        "data_file_name": data_file_name,
        "group_name": group_name,
        "data_file_columns": json.dumps(data_file_columns, ensure_ascii=False) if data_file_columns else None,
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
    columns = d.get("data_file_columns")
    if isinstance(columns, str):
        d["data_file_columns"] = json.loads(columns)
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


def get_active_embed(client: bigquery.Client, embed_id: str) -> dict[str, Any] | None:
    """Bản ghi hiện tại của embed, hoặc None nếu không tồn tại HOẶC đã bị thu hồi —
    gộp 2 điều kiện mà mọi API endpoint đều phải kiểm tra cùng nhau trước khi cho
    xem/sửa/chia sẻ 1 embed."""
    embed = get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        return None
    return embed


def list_current_embeds(client: bigquery.Client, owner_email: str | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM `{_table('v_current_embeds')}` WHERE event != 'revoked'"
    query_parameters = []
    if owner_email is not None:
        sql += " AND owner_email = @owner_email"
        query_parameters.append(bigquery.ScalarQueryParameter("owner_email", "STRING", owner_email))
    sql += " ORDER BY event_at DESC"
    job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
    rows = list(client.query(sql, job_config=job_config).result())
    return [_row_to_dict(r) for r in rows]


def list_current_embeds_by_ids(client: bigquery.Client, embed_ids: list[str]) -> list[dict[str, Any]]:
    if not embed_ids:
        return []
    sql = (
        f"SELECT * FROM `{_table('v_current_embeds')}` "
        "WHERE event != 'revoked' AND embed_id IN UNNEST(@embed_ids) ORDER BY event_at DESC"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("embed_ids", "STRING", embed_ids)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return [_row_to_dict(r) for r in rows]


def insert_share_event(
    client: bigquery.Client,
    embed_id: str,
    shared_with: str,
    permission: str,
    event: str,
    shared_by: str,
) -> None:
    row = {
        "share_id": f"{embed_id}:{shared_with.strip().lower()}:{_now()}",
        "embed_id": embed_id,
        "shared_with": shared_with.strip().lower(),
        "permission": permission,
        "event": event,
        "shared_by": shared_by,
        "event_at": _now(),
    }
    table_id = _table("embed_shares")
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Ghi {table_id} thất bại: {errors}")


def list_shares_for_embed(client: bigquery.Client, embed_id: str) -> list[dict[str, Any]]:
    """Các share đang hiệu lực (chưa 'unshared') của 1 embed — dùng cho panel Chia sẻ."""
    sql = (
        f"SELECT * FROM `{_table('v_current_embed_shares')}` "
        "WHERE embed_id = @embed_id AND event = 'shared' ORDER BY event_at DESC"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("embed_id", "STRING", embed_id)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return [dict(r.items()) for r in rows]


def get_shared_permissions_for_user(client: bigquery.Client, user: str) -> dict[str, str]:
    """embed_id -> permission ('view'|'edit') cho các embed đã share cho user này, kể
    cả share '*' (toàn bộ user nội bộ). Nếu 1 embed có cả share riêng lẫn share '*'
    với permission khác nhau, lấy quyền cao hơn (edit > view)."""
    sql = (
        f"SELECT embed_id, permission FROM `{_table('v_current_embed_shares')}` "
        "WHERE event = 'shared' AND shared_with IN (@user, '*')"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("user", "STRING", user.strip().lower())]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    result: dict[str, str] = {}
    for r in rows:
        embed_id, permission = r["embed_id"], r["permission"]
        if embed_id not in result or (permission == "edit" and result[embed_id] == "view"):
            result[embed_id] = permission
    return result


def get_share_permission(client: bigquery.Client, embed_id: str, user: str) -> str | None:
    return get_shared_permissions_for_user(client, user).get(embed_id)


def list_embed_events(client: bigquery.Client, limit: int = 500) -> list[dict[str, Any]]:
    """Toàn bộ lịch sử (created/updated/revoked), MỌI user — dùng cho trang admin
    theo dõi ai đã nhúng link nào, khi nào (khác list_current_embeds() chỉ trả bản
    ghi mới nhất/còn hiệu lực)."""
    sql = f"SELECT * FROM `{_table('embeds')}` ORDER BY event_at DESC LIMIT @limit"
    job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)])
    rows = list(client.query(sql, job_config=job_config).result())
    return [_row_to_dict(r) for r in rows]
