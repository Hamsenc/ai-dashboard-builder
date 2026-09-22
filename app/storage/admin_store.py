"""Repository cho trang admin (/admin.html): login log (đọc-only phía app, chỉ ghi
lúc callback OAuth) + user_roles (cấp/thu hồi quyền admin/embed). Tách khỏi
bq_store.py (module đó cam kết insert-only/không đọc) vì admin cần đọc lại lịch sử
đăng nhập, embed events, và role hiện tại của từng người — cùng lý do embeds_store.py
tách riêng khỏi bq_store.py."""

from __future__ import annotations

import uuid
from typing import Any

from google.cloud import bigquery
from storage._common import now as _now
from storage._common import table as _table


def insert_login(client: bigquery.Client, email: str, name: str | None, lark_user_id: str | None) -> None:
    row = {
        "login_id": str(uuid.uuid4()),
        "email": email,
        "name": name,
        "lark_user_id": lark_user_id,
        "created_at": _now(),
    }
    table_id = _table("login_log")
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Ghi {table_id} thất bại: {errors}")


def list_logins(client: bigquery.Client, limit: int = 300) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM `{_table('login_log')}` ORDER BY created_at DESC LIMIT @limit"
    job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)])
    rows = list(client.query(sql, job_config=job_config).result())
    return [dict(r.items()) for r in rows]


def insert_role_event(client: bigquery.Client, user_email: str, role: str, event: str, granted_by: str) -> None:
    row = {
        "role_event_id": str(uuid.uuid4()),
        "user_email": user_email.strip().lower(),
        "role": role,
        "event": event,
        "granted_by": granted_by,
        "event_at": _now(),
    }
    table_id = _table("user_roles")
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Ghi {table_id} thất bại: {errors}")


def get_active_roles(client: bigquery.Client, user_email: str) -> set[str]:
    sql = (
        f"SELECT role FROM `{_table('v_current_user_roles')}` "
        "WHERE user_email = @email AND event = 'granted'"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", user_email.strip().lower())]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return {r["role"] for r in rows}


def get_latest_role_event(client: bigquery.Client, user_email: str, role: str) -> dict[str, Any] | None:
    """Sự kiện mới nhất của 1 user cho 1 role cụ thể — 'granted' | 'revoked' |
    'requested', hoặc None nếu chưa từng có sự kiện nào. Dùng để tự phục vụ nút
    "Yêu cầu cấp quyền" (không request lại nếu đã granted/đang requested)."""
    sql = (
        f"SELECT * FROM `{_table('v_current_user_roles')}` "
        "WHERE user_email = @email AND role = @role"
    )
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("email", "STRING", user_email.strip().lower()),
        bigquery.ScalarQueryParameter("role", "STRING", role),
    ])
    rows = list(client.query(sql, job_config=job_config).result())
    return dict(rows[0].items()) if rows else None


def list_current_roles(client: bigquery.Client) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM `{_table('v_current_user_roles')}` WHERE event = 'granted' ORDER BY user_email, role"
    rows = list(client.query(sql).result())
    return [dict(r.items()) for r in rows]


def list_pending_role_requests(client: bigquery.Client) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM `{_table('v_current_user_roles')}` WHERE event = 'requested' ORDER BY event_at"
    rows = list(client.query(sql).result())
    return [dict(r.items()) for r in rows]


def list_table_usage_summary(client: bigquery.Client, days: int = 30) -> dict[str, list[dict[str, Any]]]:
    """Top bảng được xem/preview nhiều nhất + top user active nhất trong N ngày gần
    nhất, đọc từ data_access_log (ghi bởi bq_store.insert_data_access() mỗi lần ai
    xem chi tiết/preview 1 bảng ở Tư vấn chọn bảng — xem app/api/catalog.py). Đặt ở
    đây thay vì bq_store.py vì module đó cam kết insert-only/không đọc."""
    job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)])
    tables_sql = (
        "SELECT table_id, COUNT(*) AS access_count, COUNT(DISTINCT created_by) AS user_count, "
        "MAX(created_at) AS last_accessed_at "
        f"FROM `{_table('data_access_log')}` "
        "WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY) "
        "GROUP BY table_id ORDER BY access_count DESC LIMIT 50"
    )
    users_sql = (
        "SELECT created_by, COUNT(*) AS access_count, COUNT(DISTINCT table_id) AS table_count, "
        "MAX(created_at) AS last_accessed_at "
        f"FROM `{_table('data_access_log')}` "
        "WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY) "
        "GROUP BY created_by ORDER BY access_count DESC LIMIT 50"
    )
    tables = [dict(r.items()) for r in client.query(tables_sql, job_config=job_config).result()]
    users = [dict(r.items()) for r in client.query(users_sql, job_config=job_config).result()]
    return {"tables": tables, "users": users}
