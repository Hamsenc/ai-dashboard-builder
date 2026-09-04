"""Đọc config từ env var — 1 chỗ duy nhất, tránh os.environ[...] rải rác khắp nơi."""

from __future__ import annotations

import os


class Config:
    GCP_PROJECT = os.environ.get("GCP_PROJECT", "surya-495408")
    BQ_APP_DATASET = os.environ.get("BQ_APP_DATASET", "12_data_agent_log")
    BQ_APP_TABLE_PREFIX = os.environ.get("BQ_APP_TABLE_PREFIX", "raw_dashboard_builder_")
    CATALOG_GCS_BUCKET = os.environ.get("CATALOG_GCS_BUCKET", "surya-495408-dashboard-builder-catalog")
    SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
    # Chưa có Lark OAuth thật (Phase 9) — dùng header X-Dev-User tạm, mặc định giá trị
    # này khi header vắng mặt. PHẢI thay bằng identity thật trước khi đưa vào dùng thật.
    DEV_USER_FALLBACK = os.environ.get("DEV_USER_FALLBACK", "dev@local")
