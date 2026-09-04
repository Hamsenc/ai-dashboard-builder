"""Thực thi SQL đã qua validator lên BigQuery — dùng chung cho cả đường Build lần
đầu, nút Refresh (chạy lại y nguyên SQL đã lưu), và bộ lọc ngày sống (chạy lại y
nguyên SQL nhưng đổi giá trị @start_date/@end_date, không qua LLM).

Luôn dry-run trước để biết số byte sẽ quét (chặn sớm nếu vượt ngưỡng cấu hình), rồi
mới chạy thật với maximum_bytes_billed làm giới hạn cứng do chính BigQuery enforce —
lớp phòng thủ độc lập với ước lượng dry-run (dry-run có thể lệch nhẹ so với thực tế)."""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass

from google.cloud import bigquery


class QueryTooExpensiveError(RuntimeError):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict]
    bytes_processed: int


def _default_max_bytes() -> int:
    # Mặc định 500MB/query — đủ rộng cho dashboard nội bộ trên 10 bảng Serving hiện
    # tại (bảng lớn nhất ~vw_sales_order), chỉnh qua env nếu cần.
    return int(os.environ.get("BQ_MAX_BYTES_BILLED", str(500 * 1024 * 1024)))


def _date_params(start_date: str | None, end_date: str | None) -> list[bigquery.ScalarQueryParameter]:
    """Luôn bind @start_date/@end_date (kiểu DATE) — vô hại nếu 1 câu SQL không
    tham chiếu tới chúng (BigQuery cho phép truyền param dư không dùng tới)."""
    params = []
    if start_date:
        params.append(bigquery.ScalarQueryParameter("start_date", "DATE", start_date))
    if end_date:
        params.append(bigquery.ScalarQueryParameter("end_date", "DATE", end_date))
    return params


def dry_run_bytes(client: bigquery.Client, sql: str, query_parameters: list | None = None) -> int:
    job_config = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False, query_parameters=query_parameters or []
    )
    job = client.query(sql, job_config=job_config)
    return job.total_bytes_processed


def execute(
    client: bigquery.Client,
    sql: str,
    max_bytes_billed: int | None = None,
    query_parameters: list | None = None,
) -> QueryResult:
    max_bytes_billed = max_bytes_billed or _default_max_bytes()
    query_parameters = query_parameters or []

    estimated_bytes = dry_run_bytes(client, sql, query_parameters)
    if estimated_bytes > max_bytes_billed:
        raise QueryTooExpensiveError(
            f"Query ước tính quét {estimated_bytes:,} bytes, vượt ngưỡng cho phép "
            f"{max_bytes_billed:,} bytes. Bị chặn trước khi chạy thật."
        )

    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=max_bytes_billed, query_parameters=query_parameters
    )
    job = client.query(sql, job_config=job_config)
    result = job.result()

    columns = [field.name for field in result.schema]
    rows = [dict(row.items()) for row in result]

    return QueryResult(columns=columns, rows=rows, bytes_processed=job.total_bytes_processed or 0)


def run_queries_for_render(
    client: bigquery.Client,
    sql_per_kpi: list[dict],
    start_date: str | datetime.date | None = None,
    end_date: str | datetime.date | None = None,
) -> list[dict]:
    """Dùng chung cho Build lần đầu (blueprint.py), Refresh, và filter theo ngày
    (dashboard.py) — chạy từng SQL đã lưu, trả list JSON-serializable sẵn để trả
    thẳng qua API. start_date/end_date bind vào @start_date/@end_date nếu SQL có
    dùng — không truyền gì thì chạy y nguyên SQL như cũ (Refresh không đổi phạm vi)."""
    params = _date_params(
        start_date.isoformat() if hasattr(start_date, "isoformat") else start_date,
        end_date.isoformat() if hasattr(end_date, "isoformat") else end_date,
    )
    results = []
    for q in sql_per_kpi:
        r = execute(client, q["sql"], query_parameters=params)
        results.append({
            "kpi_name": q["kpi_name"],
            "x_field": q["x_field"],
            "y_field": q["y_field"],
            "series_field": q.get("series_field") or "",
            "rows": [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
                for row in r.rows
            ],
        })
    return results
