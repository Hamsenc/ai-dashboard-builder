"""Route xem Dashboard Embed — PUBLIC, không có Depends(get_current_user) ở bất
kỳ đâu trong file này (đúng pattern app/auth/lark_oauth.py: 1 route là public chỉ
đơn giản bằng cách không khai báo dependency đó). Viewer mở qua link nhúng trong
Lark không có session cookie của app này."""

from __future__ import annotations

import datetime
import decimal
import mimetypes
import re
import time
from typing import Any

from api.catalog import get_bq_client
from config import Config
from datasource import bq_meta
from embeds import query_spec
from embeds.gcs_store import download_bytes, download_html
from execution import bq_client
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse
from storage import embeds_store

router = APIRouter(prefix="/d")

# ĐÃ THỬ chặn frame-ancestors chỉ *.larksuite.com/*.feishu.cn — test thật trên Lark
# (block "Embeds") bị chặn "refused to connect", trong khi mở thẳng URL bằng trình
# duyệt thường thì chạy bình thường (đã xác nhận không phải lỗi khác). Không biết
# chắc origin thật Lark dùng để tải iframe (có thể qua domain trung gian/sandbox
# khác), nên bỏ hẳn giới hạn — an toàn thật sự nằm ở embed_id ngẫu nhiên không đoán
# được (bản chất là share-link, không phải domain nào được phép nhúng), không phải
# ở header này.

_BASE_TAG_RE = re.compile(r"<base\s", re.IGNORECASE)
_HEAD_RE = re.compile(r"(<head[^>]*>)", re.IGNORECASE)
_BODY_CLOSE_RE = re.compile(r"</body>", re.IGNORECASE)


def _toolbar_html(embed_id: str, embed: dict[str, Any]) -> str:
    """Toolbar cố định góc trên-phải, chèn vào MỌI dashboard tự động theo nguồn dữ
    liệu — không cần tác giả HTML tự code nút này. 'Làm mới' bypass cache 5 phút
    của /d/{id}/data (xem invalidate_cache) bằng cách reload trang với ?refresh=1.
    'Upload Excel' gọi thẳng /api/embeds/{id}/data-file có sẵn — cookie session tự
    gửi kèm nếu trình duyệt đang đăng nhập (path cookie=/api, xem auth/session.py);
    không đăng nhập/không có quyền sửa thì nhận 401/403 y hệt gọi API trực tiếp,
    không mở thêm lỗ hổng nào so với trước (embed_id vẫn phải biết để gọi được)."""
    buttons = []
    if embed.get("data_query_spec"):
        buttons.append('<button type="button" id="__ldbRefresh">↻ Làm mới</button>')
    if embed.get("data_file_gcs_path"):
        buttons.append(
            '<button type="button" id="__ldbUpload">⬆ Upload Excel</button>'
            '<input type="file" id="__ldbUploadInput" accept=".xlsx,.xls,.csv" hidden>'
        )
    if not buttons:
        return ""
    return f"""
<div id="__ldbToolbar" style="position:fixed;top:14px;right:16px;z-index:2147483647;display:flex;gap:8px;font-family:sans-serif;">
{''.join(buttons)}
</div>
<style>
#__ldbToolbar button {{ border:none;border-radius:999px;padding:8px 14px;font-size:12.5px;font-weight:700;
  background:#ede9fe;color:#7c3aed;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.12); }}
#__ldbToolbar button:hover {{ opacity:.85; }}
#__ldbToolbar button:disabled {{ opacity:.6;cursor:default; }}
</style>
<script>
(function() {{
  var refreshBtn = document.getElementById('__ldbRefresh');
  if (refreshBtn) refreshBtn.onclick = function() {{ location.href = location.pathname + '?refresh=1'; }};
  var uploadBtn = document.getElementById('__ldbUpload');
  var uploadInput = document.getElementById('__ldbUploadInput');
  if (uploadBtn) uploadBtn.onclick = function() {{ uploadInput.click(); }};
  if (uploadInput) uploadInput.onchange = function() {{
    var file = uploadInput.files[0];
    if (!file) return;
    var original = uploadBtn.textContent;
    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Đang tải lên...';
    var fd = new FormData();
    fd.append('data_file', file);
    fetch('/api/embeds/{embed_id}/data-file', {{ method: 'POST', body: fd }}).then(function(r) {{
      if (r.status === 401) throw new Error('Cần đăng nhập app trước (mở /auth/lark/login).');
      if (r.status === 403) throw new Error('Bạn không có quyền sửa dashboard này.');
      if (!r.ok) return r.json().catch(function() {{ return {{}}; }}).then(function(b) {{ throw new Error(b.detail || ('HTTP ' + r.status)); }});
      return r.json();
    }}).then(function(result) {{
      if (result && result.column_warning) alert('⚠ ' + result.column_warning);
      location.href = location.pathname + '?refresh=1';
    }}).catch(function(err) {{
      alert('Lỗi upload: ' + err.message);
      uploadBtn.disabled = false;
      uploadBtn.textContent = original;
    }});
  }};
}})();
</script>
"""


def _inject_toolbar(html: str, embed_id: str, embed: dict[str, Any]) -> str:
    toolbar = _toolbar_html(embed_id, embed)
    if not toolbar:
        return html
    match = _BODY_CLOSE_RE.search(html)
    if match:
        idx = match.start()
        return html[:idx] + toolbar + html[idx:]
    return html + toolbar


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
def view_embed(embed_id: str, refresh: bool = False):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None:
        raise HTTPException(404, "Không tìm thấy dashboard này.")
    if embed["event"] == "revoked":
        raise HTTPException(410, "Dashboard này đã bị thu hồi.")
    if refresh:
        invalidate_cache(embed_id)

    html = download_html(embed["gcs_path"])
    html = _inject_base_tag(html, embed_id)
    html = _inject_toolbar(html, embed_id, embed)
    return HTMLResponse(html)


@router.get("/{embed_id}/data-file")
def get_embed_data_file(embed_id: str):
    """File Excel/CSV user tự tải lên làm dữ liệu sống — server không parse, chỉ host
    lại nguyên bytes; dashboard tự đọc bằng SheetJS (xem .claude/skills/lark-dashboard-embed)."""
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy dashboard này.")
    if not embed.get("data_file_gcs_path"):
        raise HTTPException(404, "Dashboard này không có file dữ liệu.")

    content = download_bytes(embed["data_file_gcs_path"])
    content_type = mimetypes.guess_type(embed.get("data_file_name") or "")[0] or "application/octet-stream"
    return Response(content=content, media_type=content_type)


# Cache in-process kết quả query sống theo embed_id — dashboard chỉ load lại lúc
# mở trang/bấm refresh (không tự poll), cache chỉ để tránh nhiều người mở cùng
# lúc gây tốn BigQuery lặp lại vô ích trên 1 link công khai.
_data_cache: dict[str, dict[str, Any]] = {}


def invalidate_cache(embed_id: str) -> None:
    """Gọi sau khi sửa spec của 1 embed (api/embeds.py update_embed) để viewer thấy
    số liệu mới ngay, không phải đợi hết TTL. Chỉ xoá được cache của ĐÚNG instance
    Cloud Run đang xử lý request sửa — nếu service chạy nhiều instance, các instance
    khác vẫn có thể trả cache cũ tới khi tự hết EMBED_DATA_CACHE_TTL_SECONDS (chấp
    nhận được, không phải ranh giới bảo mật, chỉ ảnh hưởng độ mới của số liệu)."""
    _data_cache.pop(embed_id, None)


def _run_plan(client, plan: query_spec.QueryPlan) -> dict[str, Any]:
    result = bq_client.execute(
        client, plan.sql,
        max_bytes_billed=Config.EMBED_DATA_MAX_BYTES_BILLED,
        query_parameters=plan.query_parameters,
    )
    return {
        "columns": result.columns,
        "rows": [{k: _serialize_value(v) for k, v in row.items()} for row in result.rows],
    }


@router.get("/{embed_id}/data")
def get_embed_data(embed_id: str):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy dashboard này.")
    if not embed.get("data_query_spec"):
        raise HTTPException(404, "Dashboard này không có dữ liệu sống.")

    now = time.time()
    cached = _data_cache.get(embed_id)
    if cached and (now - cached["loaded_at"]) < Config.EMBED_DATA_CACHE_TTL_SECONDS:
        return cached["result"]

    spec_dict = embed["data_query_spec"]
    try:
        # Build lại từ spec đã lưu (không dùng bản build lúc upload) để luôn theo
        # schema/scope MỚI NHẤT — an toàn nếu bảng nguồn đổi cột hoặc bị rút khỏi
        # SERVING_DATASETS sau khi embed đã tạo.
        if query_spec.is_multi_spec(spec_dict):
            # Spec nhiều bảng (mới) -> payload {tên: {columns, rows}}. Spec 1 bảng
            # (cũ, embed tạo trước tính năng này) -> payload {columns, rows} phẳng
            # như trước giờ, để KHÔNG bể các dashboard đã upload/nhúng Lark từ trước.
            plans = query_spec.build_queries(client, spec_dict)
            payload = {name: _run_plan(client, plan) for name, plan in plans.items()}
        else:
            plan = query_spec.build_query(client, spec_dict)
            payload = _run_plan(client, plan)
    except bq_meta.OutOfScopeError as e:
        raise HTTPException(403, str(e)) from e
    except query_spec.InvalidQuerySpecError as e:
        raise HTTPException(400, str(e)) from e

    _data_cache[embed_id] = {"loaded_at": now, "result": payload}
    return payload
