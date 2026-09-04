"""Đọc ground-truth cột/kiểu dữ liệu từ BigQuery INFORMATION_SCHEMA cho các bảng
Serving đã được liệt kê trong Lark '02. Table Catalog' (Layer=Serving).

Đây là nguồn "sự thật" về cột — không suy luận, không phụ thuộc tài liệu Lark có
cập nhật kịp hay không.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from google.cloud import bigquery


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool
    ordinal_position: int


def fetch_columns(
    client: bigquery.Client,
    project_id: str,
    dataset_table_names: dict[str, list[str]],
) -> dict[tuple[str, str], list[ColumnInfo]]:
    """dataset_table_names: {dataset_id: [table_name, ...]}.

    Trả về map (dataset_id, table_name) -> list[ColumnInfo], sắp theo ordinal_position.
    Một dataset không tồn tại/không query được sẽ raise để job.py quyết định có nên
    fail toàn bộ sync hay không — không âm thầm bỏ qua.
    """
    result: dict[tuple[str, str], list[ColumnInfo]] = defaultdict(list)

    for dataset_id, table_names in dataset_table_names.items():
        if not table_names:
            continue
        query = f"""
            SELECT table_name, column_name, data_type, is_nullable, ordinal_position
            FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name IN UNNEST(@table_names)
            ORDER BY table_name, ordinal_position
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("table_names", "STRING", table_names),
            ]
        )
        rows = list(client.query(query, job_config=job_config).result())

        found_tables = set()
        for row in rows:
            key = (dataset_id, row.table_name)
            found_tables.add(row.table_name)
            result[key].append(
                ColumnInfo(
                    name=row.column_name,
                    data_type=row.data_type,
                    is_nullable=(row.is_nullable == "YES"),
                    ordinal_position=row.ordinal_position,
                )
            )

        missing = set(table_names) - found_tables
        if missing:
            # Lark nói bảng này Layer=Serving nhưng BigQuery không có -> lệch giữa
            # tài liệu quản trị và thực tế. job.py ghi nhận vào sync run, không
            # được âm thầm bỏ qua bảng này khỏi catalog.
            raise LookupError(
                f"Bảng khai báo Layer=Serving trong Lark nhưng không tồn tại trong "
                f"BigQuery `{project_id}.{dataset_id}`: {sorted(missing)}"
            )

    return result
