"""Xem trước dữ liệu thật của 1 bảng — để user hình dung dữ liệu trông ra sao
trước khi tự đi dựng báo cáo. Không sinh SQL cho user, không tính toán gì.

Ưu tiên dòng MỚI NHẤT + ÍT NULL NHẤT thay vì vài dòng đầu tiên storage trả về
(dòng cũ/rỗng dễ khiến user hiểu sai dữ liệu). Vì ORDER BY bắt buộc phải chạy 1
query job thật (tabledata.list không hỗ trợ ORDER BY/WHERE), preview LUÔN qua
execution.bq_client.execute() (đã có dry-run + chặn ngưỡng bytes), không còn
dùng tabledata.list miễn phí như trước.

Để giữ chi phí thấp cho bảng lớn: nếu biết cột partition, lọc về
_RECENT_WINDOW giá trị gần nhất bằng 2 bước — (1) tìm giá trị biên (rẻ, chỉ đọc
1 cột), (2) query chính với biên đó truyền qua QUERY PARAMETER (không phải
subquery lồng trong WHERE) để BigQuery áp dụng được partition pruning thật; nhét
thẳng subquery vào WHERE đã đo được là quét TOÀN BẢNG (đã test dry-run
662MB so với 26MB — xem lịch sử thay đổi)."""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from config import Config
from datasource import bq_meta
from execution import bq_client
from google.cloud import bigquery

_RECENT_WINDOW = 7  # số giá trị cột partition gần nhất coi là "mới"


def _serialize_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, bytes):
        return "<binary>"
    if isinstance(v, dict):
        return {k: _serialize_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize_value(x) for x in v]
    return v


def _null_score_expr(column_names: list[str]) -> str:
    """Càng nhiều cột KHÔNG null càng ưu tiên hiện trước — dòng dữ liệu rỗng lỗ
    chỗ dễ khiến user tưởng cả bảng thiếu dữ liệu."""
    if not column_names:
        return "0"
    return " + ".join(f"IF(`{c}` IS NOT NULL, 1, 0)" for c in column_names)


def _find_recent_boundary(client: bigquery.Client, table_id: str, partition_column: str):
    """Giá trị nhỏ nhất trong _RECENT_WINDOW giá trị LỚN NHẤT của cột partition —
    chỉ đọc 1 cột nên rẻ, dùng làm mốc WHERE ở query chính (partition pruning chỉ
    hoạt động với literal/param, KHÔNG hoạt động nếu nhét thẳng subquery này vào
    WHERE của query chính)."""
    sql = f"""
    SELECT MIN(x) AS boundary FROM (
      SELECT DISTINCT `{partition_column}` AS x FROM `{table_id}`
      ORDER BY x DESC LIMIT {_RECENT_WINDOW}
    )
    """
    result = bq_client.execute(client, sql, max_bytes_billed=Config.PREVIEW_MAX_BYTES)
    if not result.rows:
        return None
    return result.rows[0]["boundary"]


def preview_rows(client: bigquery.Client, table_id: str, limit: int | None = None) -> dict[str, Any]:
    bq_meta.assert_in_scope(table_id)
    limit = limit or Config.PREVIEW_ROW_LIMIT

    meta = bq_meta.get_table(client, table_id)
    if meta is None:
        raise LookupError(f"Không tìm thấy bảng '{table_id}' trong phạm vi Serving.")

    columns_meta = meta.get("columns", [])
    column_names = [c["name"] for c in columns_meta]
    null_score = _null_score_expr(column_names)
    partition_column = meta.get("partition_column")

    where_clause = ""
    order_clause = f"ORDER BY ({null_score}) DESC"
    query_parameters: list[bigquery.ScalarQueryParameter] = []
    ordering_note = "Ưu tiên các dòng đầy đủ dữ liệu nhất (bảng không có cột ngày/giờ rõ ràng để lọc gần đây)."

    if partition_column:
        partition_type = next((c["type"] for c in columns_meta if c["name"] == partition_column), None)
        boundary = _find_recent_boundary(client, table_id, partition_column) if partition_type else None
        if boundary is not None and partition_type:
            where_clause = f"WHERE `{partition_column}` >= @__preview_boundary"
            query_parameters.append(
                bigquery.ScalarQueryParameter("__preview_boundary", partition_type, boundary)
            )
            order_clause = f"ORDER BY `{partition_column}` DESC, ({null_score}) DESC"
            ordering_note = (
                f"Ưu tiên {_RECENT_WINDOW} giá trị `{partition_column}` gần nhất, "
                "trong đó ưu tiên dòng đầy đủ dữ liệu nhất."
            )

    sql = f"SELECT * FROM `{table_id}` {where_clause} {order_clause} LIMIT {int(limit)}"
    result = bq_client.execute(
        client, sql, max_bytes_billed=Config.PREVIEW_MAX_BYTES, query_parameters=query_parameters
    )
    columns = result.columns
    rows = [{k: _serialize_value(v) for k, v in row.items()} for row in result.rows]

    pii_note = meta.get("pii_note", "")
    column_notes = {
        c["name"]: {
            "friendly_name": c.get("friendly_name", ""),
            "description": c.get("description", ""),
            "sentinel_values": c.get("sentinel_values", []),
        }
        for c in columns_meta
    }

    return {
        "columns": columns,
        "rows": rows,
        "pii_warning": pii_note if meta.get("has_pii") else "",
        "column_notes": column_notes,
        "ordering_note": ordering_note,
    }
