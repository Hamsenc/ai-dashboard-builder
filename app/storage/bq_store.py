"""Lớp repository, insert-only, cho các bảng app trong `12_data_agent_log`
(tiền tố `raw_dashboard_builder_`).

Sau khi bỏ luồng dashboard builder, bảng `blueprints`/`builds`/`kpi_confirmations`
(+ view `v_current_blueprints`) đã xoá khỏi BigQuery và khỏi app/storage/ddl/ — không
còn hàm ghi tương ứng và không ai đọc lại dữ liệu cũ. Chỉ còn `chat_messages` (lịch sử
hội thoại Advisor) và `data_access_log` (audit ai đã xem/preview bảng nào) đang được
ghi.

Quyết định thiết kế: KHÔNG bao giờ UPDATE (BigQuery không hợp với ghi/sửa tần suất
cao kiểu app state — streaming buffer, quota DML). Mọi bảng ở đây append-only."""

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


def insert_data_access(
    client: bigquery.Client,
    created_by: str,
    table_id: str,
    action: str,
    row_count: int | None = None,
) -> None:
    """Ghi vết ai đã xem bảng/dữ liệu nào (Data Explorer chiếu dữ liệu thật, kể
    cả PII, cho mọi nhân viên đăng nhập được — cần audit trail)."""
    row = {
        "access_id": str(uuid.uuid4()),
        "created_by": created_by,
        "table_id": table_id,
        "action": action,
        "row_count": row_count,
        "created_at": _now(),
    }
    _insert(client, "data_access_log", row)


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
