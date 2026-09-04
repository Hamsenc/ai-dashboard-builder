"""Áp dụng các file DDL trong app/storage/ddl/*.sql lên BigQuery theo đúng thứ tự tên file.

Dùng lại khi cần tạo lại bảng ở project/dataset khác, hoặc sau khi sửa DDL.
Không có cơ chế migration/versioning — mỗi file dùng CREATE TABLE IF NOT EXISTS /
CREATE OR REPLACE VIEW nên chạy lại nhiều lần là an toàn (idempotent).
"""

import pathlib
import sys

from google.cloud import bigquery

DDL_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "storage" / "ddl"


def main() -> None:
    project_id = sys.argv[1] if len(sys.argv) > 1 else "surya-495408"
    client = bigquery.Client(project=project_id)

    ddl_files = sorted(DDL_DIR.glob("*.sql"))
    if not ddl_files:
        raise SystemExit(f"Không tìm thấy file .sql nào trong {DDL_DIR}")

    for path in ddl_files:
        sql = path.read_text()
        print(f"=== {path.name} ===")
        job = client.query(sql)
        job.result()
        print(f"OK: {path.name}")


if __name__ == "__main__":
    main()
