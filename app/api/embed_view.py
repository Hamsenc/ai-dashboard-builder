"""Route xem Dashboard Embed — PUBLIC, không có Depends(get_current_user) ở bất
kỳ đâu trong file này (đúng pattern app/auth/lark_oauth.py: 1 route là public chỉ
đơn giản bằng cách không khai báo dependency đó). Viewer mở qua link nhúng trong
Lark không có session cookie của app này."""

from __future__ import annotations

import datetime
import decimal
import re
import time
from typing import Any

from api.catalog import get_bq_client
from config import Config
from datasource import bq_meta
from embeds import query_spec
from embeds.gcs_store import download_html
from execution import bq_client
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from storage import embeds_store

router = APIRouter(prefix="/d")

# Chỉ cho phép Lark nhúng iframe trang này — domain khác thì không, chặn
# clickjacking/nhúng lại ở nơi không mong muốn.
_EMBED_CSP = "frame-ancestors https://*.larksuite.com https://*.feishu.cn"

_BASE_TAG_RE = re.compile(r"<base\s", re.IGNORECASE)
_HEAD_RE = re.compile(r"(<head[^>]*>)", re.IGNORECASE)


def _inject_base_tag(html: str, embed_id: str) -> str:
    """fetch('data')/<img src="..."> tương đối trong dashboard sẽ tự resolve SAI
    thành /d/data (browser bỏ segment cuối của URL hiện tại khi resolve URL tương
    đối) nếu không có <base>. Tự chèn <base href="/d/{embed_id}/"> để mọi tham
    chiếu tương đối trong HTML tác giả upload tự động đúng, không cần họ biết gì
    về URL scheme của app này. Bỏ qua nếu HTML đã tự khai báo <base> riêng."""
    if _BASE_TAG_RE.search(html):
        return html
    base_tag = f'<base href="/d/{embed_id}/">'
    match = _HEAD_RE.search(html)
    if match:
        idx = match.end()
        return html[: idx] + base_tag + html[idx:]
    return base_tag + html


def _serialize_value(v: Any) -> Any:
    # Cùng logic datasource/preview.py._serialize_value — BigQuery row có thể
    # chứa date/datetime/Decimal/bytes, không tự JSON-encode được.
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, bytes):
        return "<binary>"
    if isinstance(v, dict):
        return {k: _serialize_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize_value(x) for x in v]
    return v


@router.get("/{embed_id}")
def view_embed(embed_id: str):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None:
        raise HTTPException(404, "Không tìm thấy dashboard này.")
    if embed["event"] != "created":
        raise HTTPException(410, "Dashboard này đã bị thu hồi.")

    html = download_html(embed["gcs_path"])
    html = _inject_base_tag(html, embed_id)
    return HTMLResponse(html, headers={"Content-Security-Policy": _EMBED_CSP})


# Cache in-process kết quả query sống theo embed_id — dashboard chỉ load lại lúc
# mở trang/bấm refresh (không tự poll), cache chỉ để tránh nhiều người mở cùng
# lúc gây tốn BigQuery lặp lại vô ích trên 1 link công khai.
_data_cache: dict[str, dict[str, Any]] = {}


@router.get("/{embed_id}/data")
def get_embed_data(embed_id: str):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] != "created":
        raise HTTPException(404, "Không tìm thấy dashboard này.")
    if not embed.get("data_query_spec"):
        raise HTTPException(404, "Dashboard này không có dữ liệu sống.")

    now = time.time()
    cached = _data_cache.get(embed_id)
    if cached and (now - cached["loaded_at"]) < Config.EMBED_DATA_CACHE_TTL_SECONDS:
        return cached["result"]

    try:
        # Build lại từ spec đã lưu (không dùng bản build lúc upload) để luôn theo
        # schema/scope MỚI NHẤT — an toàn nếu bảng nguồn đổi cột hoặc bị rút khỏi
        # SERVING_DATASETS sau khi embed đã tạo.
        plan = query_spec.build_query(client, embed["data_query_spec"])
    except bq_meta.OutOfScopeError as e:
        raise HTTPException(403, str(e)) from e
    except query_spec.InvalidQuerySpecError as e:
        raise HTTPException(400, str(e)) from e

    result = bq_client.execute(
        client, plan.sql,
        max_bytes_billed=Config.EMBED_DATA_MAX_BYTES_BILLED,
        query_parameters=plan.query_parameters,
    )
    payload = {
        "columns": result.columns,
        "rows": [{k: _serialize_value(v) for k, v in row.items()} for row in result.rows],
    }

    _data_cache[embed_id] = {"loaded_at": now, "result": payload}
    return payload
