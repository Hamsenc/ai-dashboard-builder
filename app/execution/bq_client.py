"""Thực thi SQL lên BigQuery cho đường xem trước dữ liệu của VIEW (datasource/
preview.py) — BASE TABLE dùng tabledata.list, không qua module này.

Luôn dry-run trước để biết số byte sẽ quét (chặn sớm nếu vượt ngưỡng cấu hình), rồi
mới chạy thật với maximum_bytes_billed làm giới hạn cứng do chính BigQuery enforce —
lớp phòng thủ độc lập với ước lượng dry-run (dry-run có thể lệch nhẹ so với thực tế)."""

from __future__ import annotations

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
    # Mặc định 500MB/query — chỉnh qua env nếu cần.
    return int(os.environ.get("BQ_MAX_BYTES_BILLED", str(500 * 1024 * 1024)))


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
