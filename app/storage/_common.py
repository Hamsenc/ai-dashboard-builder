"""Helper dùng chung cho mọi repository trong storage/ — tên bảng app (theo prefix
raw_dashboard_builder_) và timestamp UTC hiện tại theo đúng định dạng BigQuery cần."""

from __future__ import annotations

import os
from datetime import datetime, timezone


def table(name: str) -> str:
    project = os.environ["GCP_PROJECT"]
    dataset = os.environ["BQ_APP_DATASET"]
    prefix = os.environ.get("BQ_APP_TABLE_PREFIX", "raw_dashboard_builder_")
    return f"{project}.{dataset}.{prefix}{name}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
