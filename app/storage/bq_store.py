"""Lớp repository, insert-only, cho các bảng app trong `12_data_agent_log`
(tiền tố `raw_dashboard_builder_`).

Quyết định thiết kế quan trọng: KHÔNG bao giờ UPDATE (BigQuery không hợp với ghi/sửa
tần suất cao kiểu app state — streaming buffer, quota DML). Hệ quả:
- Blueprint CHỈ được ghi vào bảng `blueprints` tại thời điểm user bấm Approve — trước
  đó (đang ở bước Clarify/đề xuất) blueprint chỉ tồn tại trong bộ nhớ phiên chat, chưa
  persist. Vì vậy mọi row trong `blueprints` có status='approved' ngay từ lúc insert
  (approved_by/approved_at set cùng lúc với created_by/created_at).
- "Bản hiện hành" của 1 dashboard_id = version lớn nhất, lấy qua view
  `raw_dashboard_builder_v_current_blueprints` — không cần đánh dấu 'superseded' bằng
  UPDATE, version mới hơn tự nhiên trở thành hiện hành.
- Nếu sau này cần "archive" 1 dashboard, cũng chỉ cần insert thêm 1 version mới với
  status='archived' — vẫn append-only."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

_TABLE_PREFIX_ENV = "BQ_APP_TABLE_PREFIX"


def _table(name: str) -> str:
    project = os.environ["GCP_PROJECT"]
    dataset = os.environ["BQ_APP_DATASET"]
    prefix = os.environ.get(_TABLE_PREFIX_ENV, "raw_dashboard_builder_")
    return f"{project}.{dataset}.{prefix}{name}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert(client: bigquery.Client, table_name: str, row: dict[str, Any]) -> None:
    table_id = _table(table_name)
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Ghi {table_id} thất bại: {errors}")


def _get_latest_version(client: bigquery.Client, dashboard_id: str) -> int:
    query = f"""
        SELECT MAX(version) AS max_version
        FROM `{_table('blueprints')}`
        WHERE dashboard_id = @dashboard_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("dashboard_id", "STRING", dashboard_id)]
    )
    rows = list(client.query(query, job_config=job_config).result())
    max_version = rows[0]["max_version"] if rows else None
    return max_version or 0


def insert_approved_blueprint(
    client: bigquery.Client,
    dashboard_id: str,
    spec: dict[str, Any],
    catalog_version_used: str,
    created_by: str,
    parent_blueprint_id: str | None = None,
    is_structural_change: bool | None = None,
    change_summary: str | None = None,
) -> dict[str, Any]:
    """Insert 1 blueprint MỚI ĐÃ Ở TRẠNG THÁI APPROVED (xem docstring module)."""
    version = _get_latest_version(client, dashboard_id) + 1
    now = _now()
    row = {
        "blueprint_id": str(uuid.uuid4()),
        "dashboard_id": dashboard_id,
        "version": version,
        "parent_blueprint_id": parent_blueprint_id,
        "status": "approved",
        "is_structural_change": is_structural_change,
        "change_summary": change_summary,
        "spec": json.dumps(spec, ensure_ascii=False),
        "catalog_version_used": catalog_version_used,
        "created_by": created_by,
        "created_at": now,
        "approved_by": created_by,
        "approved_at": now,
    }
    _insert(client, "blueprints", row)
    return row


def get_current_blueprint(client: bigquery.Client, dashboard_id: str) -> dict[str, Any] | None:
    query = f"""
        SELECT * FROM `{_table('v_current_blueprints')}`
        WHERE dashboard_id = @dashboard_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("dashboard_id", "STRING", dashboard_id)]
    )
    rows = list(client.query(query, job_config=job_config).result())
    if not rows:
        return None
    d = dict(rows[0].items())
    d["spec"] = json.loads(d["spec"]) if isinstance(d["spec"], str) else d["spec"]
    return d


def list_my_dashboards(client: bigquery.Client, created_by: str) -> list[dict[str, Any]]:
    query = f"""
        SELECT dashboard_id, version, spec, status, created_at, approved_at
        FROM `{_table('v_current_blueprints')}`
        WHERE created_by = @created_by AND status != 'archived'
        ORDER BY approved_at DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("created_by", "STRING", created_by)]
    )
    out = []
    for row in client.query(query, job_config=job_config).result():
        d = dict(row.items())
        d["spec"] = json.loads(d["spec"]) if isinstance(d["spec"], str) else d["spec"]
        out.append(d)
    return out


def insert_build(
    client: bigquery.Client,
    blueprint_id: str,
    dashboard_id: str,
    sql_per_kpi: list[dict[str, Any]],
    validator_status: str,
    validator_report: dict[str, Any],
    catalog_version_used: str,
    created_by: str,
    default_start_date: str,
    default_end_date: str,
    status: str = "active",
) -> dict[str, Any]:
    row = {
        "build_id": str(uuid.uuid4()),
        "blueprint_id": blueprint_id,
        "dashboard_id": dashboard_id,
        "status": status,
        "sql_per_kpi": json.dumps(sql_per_kpi, ensure_ascii=False),
        "validator_status": validator_status,
        "validator_report": json.dumps(validator_report, ensure_ascii=False),
        "catalog_version_used": catalog_version_used,
        "created_by": created_by,
        "created_at": _now(),
        "default_start_date": default_start_date,
        "default_end_date": default_end_date,
    }
    _insert(client, "builds", row)
    return row


def get_current_build(client: bigquery.Client, dashboard_id: str) -> dict[str, Any] | None:
    query = f"""
        SELECT * FROM `{_table('builds')}`
        WHERE dashboard_id = @dashboard_id AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("dashboard_id", "STRING", dashboard_id)]
    )
    rows = list(client.query(query, job_config=job_config).result())
    if not rows:
        return None
    d = dict(rows[0].items())
    # Cột JSON: BigQuery client trả sẵn dạng đã parse (list/dict), KHÔNG phải string
    # — khác insert_rows_json lúc ghi (nhận string). json.loads chỉ khi còn là string.
    if isinstance(d["sql_per_kpi"], str):
        d["sql_per_kpi"] = json.loads(d["sql_per_kpi"])
    if isinstance(d["validator_report"], str):
        d["validator_report"] = json.loads(d["validator_report"])
    return d


def insert_kpi_confirmation(
    client: bigquery.Client,
    blueprint_id: str,
    dashboard_id: str,
    kpi_name: str,
    kpi_status_at_confirmation: str,
    kpi_formula_text: str,
    catalog_version_used: str,
    confirmed_by: str,
    action: str = "initial_confirm",
    kpi_table_id: str | None = None,
    kpi_caveat_text: str | None = None,
) -> None:
    row = {
        "confirmation_id": str(uuid.uuid4()),
        "blueprint_id": blueprint_id,
        "dashboard_id": dashboard_id,
        "kpi_name": kpi_name,
        "kpi_table_id": kpi_table_id,
        "kpi_status_at_confirmation": kpi_status_at_confirmation,
        "kpi_formula_text": kpi_formula_text,
        "kpi_caveat_text": kpi_caveat_text,
        "catalog_version_used": catalog_version_used,
        "action": action,
        "confirmed_by": confirmed_by,
        "confirmed_at": _now(),
    }
    _insert(client, "kpi_confirmations", row)


def insert_chat_message(
    client: bigquery.Client,
    session_id: str,
    turn_index: int,
    role: str,
    content: str | None,
    created_by: str,
    dashboard_id: str | None = None,
    structured_payload: dict[str, Any] | None = None,
    llm_model: str | None = None,
) -> None:
    row = {
        "message_id": str(uuid.uuid4()),
        "session_id": session_id,
        "dashboard_id": dashboard_id,
        "turn_index": turn_index,
        "role": role,
        "content": content,
        "structured_payload": json.dumps(structured_payload, ensure_ascii=False) if structured_payload else None,
        "llm_model": llm_model,
        "created_by": created_by,
        "created_at": _now(),
    }
    _insert(client, "chat_messages", row)
