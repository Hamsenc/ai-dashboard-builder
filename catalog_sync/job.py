"""Entry point của catalog sync job: đọc Lark '02'+'04' + BigQuery INFORMATION_SCHEMA,
gộp thành 1 catalog JSON, ghi lên GCS, ghi 1 dòng audit vào
`12_data_agent_log.raw_dashboard_builder_catalog_sync_runs`.

CHƯA CHẠY THỬ được end-to-end trong phiên này — cần LARK_APP_ID/LARK_APP_SECRET của
1 Lark app đã được cấp quyền bitable:app:readonly trên base
AcITbzsvraObhisDdQXlO6tggkd (job chạy không người trực nên không dùng được OAuth theo
user như lúc khảo sát). Logic gộp (merge.py) đã test bằng dữ liệu Lark thật, và
information_schema.py đã chạy thật trên BigQuery — phần chưa verify được là đúng lệnh
gọi HTTP tới Lark REST API trong lark_client.list_records().

Chạy tay: `python catalog_sync/job.py` (đọc config từ env var, xem .env.example).
Không override latest.json nếu sanity check thất bại — tránh làm hỏng catalog đang
sống chỉ vì 1 lần Lark API lỗi/trả về thiếu.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import uuid

from google.cloud import bigquery, storage

from information_schema import fetch_columns
from lark_client import get_tenant_access_token, list_records
from merge import build_catalog

LARK_TABLE_02_ID = "tblA61jccZSexp2F"  # "02. Table Catalog"
LARK_TABLE_03_ID = "tblfoft2R9IZcl00"  # "03. Column Dictionary"
LARK_TABLE_04_ID = "tblNr2LJO47ClgWW"  # "04. Business Logic - KPI"

# Đối chiếu con số đã biết thật (khảo sát 2026-09-03) — sync không được coi là thành
# công nếu lệch xa các con số này, vì nhiều khả năng là Lark API trả về thiếu/lỗi chứ
# không phải catalog thật sự đổi đột ngột.
EXPECTED_TABLE_COUNT = 10
EXPECTED_KPI_TOTAL = 25  # kpis + out_of_scope_kpis cộng lại


def _table_ids_by_dataset(table_records: list[dict]) -> dict[str, list[str]]:
    from lark_client import field_text

    result: dict[str, list[str]] = {}
    for rec in table_records:
        f = rec["fields"]
        if field_text(f.get("Layer")) != "Serving":
            continue
        table_id = field_text(f.get("Table_ID"))
        if not table_id:
            continue
        _project, dataset, table_name = table_id.split(".")
        result.setdefault(dataset, []).append(table_name)
    return result


def run(project_id: str, bq_dataset: str, table_prefix: str, gcs_bucket: str) -> dict:
    lark_host = os.environ["LARK_OAUTH_HOST"]
    lark_app_id = os.environ["LARK_APP_ID"]
    lark_app_secret = os.environ["LARK_APP_SECRET"]
    lark_base_token = os.environ["LARK_BASE_TOKEN"]

    token = get_tenant_access_token(lark_host, lark_app_id, lark_app_secret)
    table_records = list(list_records(lark_host, token, lark_base_token, LARK_TABLE_02_ID))
    column_dict_records = list(list_records(lark_host, token, lark_base_token, LARK_TABLE_03_ID))
    kpi_records = list(list_records(lark_host, token, lark_base_token, LARK_TABLE_04_ID))

    bq_client = bigquery.Client(project=project_id)
    info_schema = fetch_columns(bq_client, project_id, _table_ids_by_dataset(table_records))

    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    catalog = build_catalog(
        table_records, kpi_records, info_schema, generated_at,
        column_dict_records=column_dict_records,
    )

    table_count = len(catalog["tables"])
    kpi_total = len(catalog["kpis"]) + len(catalog["out_of_scope_kpis"])
    sanity_ok = table_count == EXPECTED_TABLE_COUNT and kpi_total == EXPECTED_KPI_TOTAL
    status = "success" if sanity_ok else "partial"

    sync_id = str(uuid.uuid4())
    gcs_uri = f"gs://{gcs_bucket}/catalog/{generated_at}.json"

    if sanity_ok:
        _upload_json(gcs_bucket, f"catalog/{generated_at}.json", catalog)
        _upload_json(gcs_bucket, "catalog/latest.json", catalog)
    else:
        # Vẫn ghi bản có version riêng để điều tra, nhưng KHÔNG đè latest.json —
        # Planner phải tiếp tục dùng bản cũ còn đáng tin hơn là 1 bản thiếu dữ liệu.
        _upload_json(gcs_bucket, f"catalog/{generated_at}.json", catalog)

    error_message = None
    if not sanity_ok:
        error_message = (
            f"Sanity check thất bại: table_count={table_count} (kỳ vọng "
            f"{EXPECTED_TABLE_COUNT}), kpi_total={kpi_total} (kỳ vọng {EXPECTED_KPI_TOTAL}). "
            "KHÔNG cập nhật latest.json."
        )
        print(f"CẢNH BÁO: {error_message}", file=sys.stderr)

    _write_sync_run_row(
        bq_client,
        project_id,
        bq_dataset,
        table_prefix,
        sync_id=sync_id,
        generated_at=generated_at,
        gcs_uri=gcs_uri,
        table_count=table_count,
        kpi_count=kpi_total,
        status=status,
        error_message=error_message,
    )

    return catalog


def _upload_json(bucket_name: str, blob_path: str, data: dict) -> None:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json"
    )


def _write_sync_run_row(
    client: bigquery.Client,
    project_id: str,
    dataset: str,
    table_prefix: str,
    **row: object,
) -> None:
    table_id = f"{project_id}.{dataset}.{table_prefix}catalog_sync_runs"
    row["triggered_by"] = os.environ.get("TRIGGERED_BY", "manual")
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Ghi catalog_sync_runs thất bại: {errors}")


if __name__ == "__main__":
    catalog = run(
        project_id=os.environ.get("GCP_PROJECT", "surya-495408"),
        bq_dataset=os.environ.get("BQ_APP_DATASET", "12_data_agent_log"),
        table_prefix=os.environ.get("BQ_APP_TABLE_PREFIX", "raw_dashboard_builder_"),
        gcs_bucket=os.environ.get(
            "CATALOG_GCS_BUCKET", "surya-495408-dashboard-builder-catalog"
        ),
    )
    print(
        f"OK: {len(catalog['tables'])} bảng, {len(catalog['kpis'])} KPI in-scope, "
        f"{len(catalog['out_of_scope_kpis'])} KPI out-of-scope."
    )
