"""Đọc/ghi file HTML dashboard trên GCS — bucket luôn PRIVATE, chỉ server chạm
tới (giống pattern app/catalog/client.py cho bucket catalog). Browser không bao
giờ có địa chỉ GCS trực tiếp, chỉ có link /d/{embed_id} do app proxy."""

from __future__ import annotations

from config import Config
from google.cloud import storage

_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def upload_html(gcs_path: str, html: str) -> None:
    bucket = _get_client().bucket(Config.EMBEDS_GCS_BUCKET)
    bucket.blob(gcs_path).upload_from_string(html, content_type="text/html; charset=utf-8")


def download_html(gcs_path: str) -> str:
    bucket = _get_client().bucket(Config.EMBEDS_GCS_BUCKET)
    return bucket.blob(gcs_path).download_as_text()
