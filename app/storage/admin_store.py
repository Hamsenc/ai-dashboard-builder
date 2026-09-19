"""Repository cho trang admin (/admin.html): login log (đọc-only phía app, chỉ ghi
lúc callback OAuth) + user_roles (cấp/thu hồi quyền admin/embed). Tách khỏi
bq_store.py (module đó cam kết insert-only/không đọc) vì admin cần đọc lại lịch sử
đăng nhập, embed events, và role hiện tại của từng người — cùng lý do embeds_store.py
tách riêng khỏi bq_store.py."""

from __future__ import annotations

import os
import uuid
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


def list_current_roles(client: bigquery.Client) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM `{_table('v_current_user_roles')}` WHERE event = 'granted' ORDER BY user_email, role"
    rows = list(client.query(sql).result())
    return [dict(r.items()) for r in rows]
