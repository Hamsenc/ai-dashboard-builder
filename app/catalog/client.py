"""Đọc catalog JSON từ GCS (bản do catalog_sync ghi ra), cache trong process với TTL.

Planner/Builder chỉ được đọc catalog qua module này — không bao giờ tự gọi thẳng
BigQuery INFORMATION_SCHEMA hay Lark API giữa lúc chat (đúng thiết kế: catalog là
snapshot đã được duyệt qua sanity check, không phải tra cứu sống)."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from google.cloud import storage

_cache: dict[str, Any] = {"data": None, "loaded_at": 0.0}
_TTL_SECONDS = 600  # 10 phút — đủ mới cho 1 job sync chạy hằng ngày, tránh gọi GCS mỗi request


def load_catalog(force_reload: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force_reload and _cache["data"] is not None and (now - _cache["loaded_at"]) < _TTL_SECONDS:
        return _cache["data"]

    bucket_name = os.environ["CATALOG_GCS_BUCKET"]
    client = storage.Client()
    blob = client.bucket(bucket_name).blob("catalog/latest.json")
    raw = blob.download_as_text()
    data = json.loads(raw)

    _cache["data"] = data
    _cache["loaded_at"] = now
    return data
