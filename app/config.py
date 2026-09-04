"""Đọc config từ env var — 1 chỗ duy nhất, tránh os.environ[...] rải rác khắp nơi."""

from __future__ import annotations

import os


class Config:
    GCP_PROJECT = os.environ.get("GCP_PROJECT", "surya-495408")
    BQ_APP_DATASET = os.environ.get("BQ_APP_DATASET", "12_data_agent_log")
    BQ_APP_TABLE_PREFIX = os.environ.get("BQ_APP_TABLE_PREFIX", "raw_dashboard_builder_")
    CATALOG_GCS_BUCKET = os.environ.get("CATALOG_GCS_BUCKET", "surya-495408-dashboard-builder-catalog")

    # Hàng rào cứng phạm vi dữ liệu: CHỈ 3 dataset tầng Serving này được phép đọc
    # metadata/preview. datasource/bq_meta.assert_in_scope() kiểm tra mọi table_id
    # nhận từ client với danh sách này trước khi chạm BigQuery.
    SERVING_DATASETS = [
        d.strip()
        for d in os.environ.get(
            "SERVING_DATASETS", "00_serving_sales,00_serving_inventory,00_serving_operation"
        ).split(",")
        if d.strip()
    ]
    # Preview dùng tabledata.list (không tốn quota) cho BASE TABLE; VIEW phải chạy
    # SELECT * LIMIT qua execution.bq_client.execute(), giới hạn bytes riêng cho
    # đường này (nhỏ hơn hẳn BQ_MAX_BYTES_BILLED vì chỉ cần vài chục dòng).
    PREVIEW_ROW_LIMIT = int(os.environ.get("PREVIEW_ROW_LIMIT", "20"))
    PREVIEW_MAX_BYTES = int(os.environ.get("PREVIEW_MAX_BYTES", str(200 * 1024 * 1024)))

    SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
    # Chưa có Lark OAuth thật (Phase 9) — dùng header X-Dev-User tạm, mặc định giá trị
    # này khi header vắng mặt. PHẢI thay bằng identity thật trước khi đưa vào dùng thật.
    DEV_USER_FALLBACK = os.environ.get("DEV_USER_FALLBACK", "dev@local")
