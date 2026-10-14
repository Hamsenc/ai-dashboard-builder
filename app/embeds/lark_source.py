"""Nguồn "dữ liệu sống" từ Lark Base (Bitable) — đọc bằng tenant_access_token của
chính app (LARK_APP_ID/LARK_APP_SECRET, bot "Bùi Trường Linh - Data Assistant").
Mỗi file Base muốn dùng phải được share cho bot đó, nếu không Lark trả lỗi quyền.

Gọi REST giống catalog_sync/lark_client.py nhưng phải chép lại phần token/phân trang:
Dockerfile chính chỉ COPY app/, không import được code trong catalog_sync/.
# ponytail: chỉ nhận link /base/..., Base nằm trong Wiki (/wiki/...) cần thêm bước
# wiki/v2/spaces/get_node để ra obj_token — thêm khi có người cần.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

MAX_SOURCES = 5
MAX_ROWS = 20000  # cùng trần với query_spec._MAX_LIMIT của nguồn BigQuery
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BASE_PATH_RE = re.compile(r"/base/([A-Za-z0-9]+)")
_DATE_TYPES = {5, 1001, 1002}  # DateTime, CreatedTime, ModifiedTime — Lark trả epoch ms
_NUMBER_TYPE = 2
_VN_TZ = dt.timezone(dt.timedelta(hours=7))


class LarkSourceError(ValueError):
    pass


def parse_url(url: str) -> tuple[str, str, str | None]:
    """Link Base copy từ trình duyệt -> (base_token, table_id, view_id|None)."""
    parsed = urlparse(url.strip())
    m = _BASE_PATH_RE.search(parsed.path)
    qs = parse_qs(parsed.query)
    table_id = (qs.get("table") or [None])[0]
    if not m or not table_id:
        raise LarkSourceError(
            f"Link không hợp lệ: {url!r} — cần link Lark Base dạng .../base/<token>?table=tbl... "
            "(mở đúng bảng trong Base rồi copy link trên thanh địa chỉ)."
        )
    return m.group(1), table_id, (qs.get("view") or [None])[0]


def validate_sources(sources: Any) -> dict[str, str]:
    """{tên: link} — tên dùng làm key trong payload của /d/{id}/lark-data."""
    if not isinstance(sources, dict) or not sources:
        raise LarkSourceError("data_lark_sources phải là object {tên: link Lark Base} và không rỗng.")
    if len(sources) > MAX_SOURCES:
        raise LarkSourceError(f"Tối đa {MAX_SOURCES} bảng Lark/dashboard.")
    for name, url in sources.items():
        if not _NAME_RE.match(name):
            raise LarkSourceError(f"Tên '{name}' không hợp lệ — chỉ chữ/số/gạch dưới, không bắt đầu bằng số.")
        if not isinstance(url, str):
            raise LarkSourceError(f"Link của '{name}' phải là chuỗi.")
        parse_url(url)
    return sources


def _host() -> str:
    return os.environ.get("LARK_OAUTH_HOST", "https://open.larksuite.com")


def get_token() -> str:
    resp = httpx.post(
        f"{_host()}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": os.environ["LARK_APP_ID"], "app_secret": os.environ["LARK_APP_SECRET"]},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise LarkSourceError(f"Không lấy được tenant_access_token: {data.get('msg')}")
    return data["tenant_access_token"]


def _get(token: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.get(
        f"{_host()}/open-apis/bitable/v1/apps/{path}",
        headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30,
    )
    payload = resp.json()
    if payload.get("code") != 0:
        raise LarkSourceError(
            f"Lark từ chối đọc ({payload.get('code')} {payload.get('msg')}) — kiểm tra link đúng bảng, "
            "và file Base đã share cho bot 'Bùi Trường Linh' chưa."
        )
    return payload["data"]


def _paged(token: str, path: str, params: dict[str, Any], limit: int):
    page_token, count = None, 0
    while True:
        data = _get(token, path, {**params, "page_size": 500, **({"page_token": page_token} if page_token else {})})
        for item in data.get("items") or []:
            yield item
            count += 1
            if count >= limit:
                return
        if not data.get("has_more"):
            return
        page_token = data.get("page_token")


def _text(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(t for t in (_text(x) for x in v) if t)
    if isinstance(v, dict):
        for key in ("text", "name", "link", "email"):
            if key in v:
                return str(v[key])
        if "text_arr" in v:
            return ", ".join(map(str, v["text_arr"]))
        return str(v)
    return "" if v is None else str(v)


def normalize_cell(v: Any, field_type: int) -> Any:
    """Giá trị thô của Bitable API -> giá trị phẳng dùng được ngay trong JS (giống
    payload BigQuery): số giữ số, ngày ra 'YYYY-MM-DD[ HH:MM:SS]' giờ VN, còn lại ra text."""
    if v is None:
        return None
    if isinstance(v, dict) and "value" in v:  # lookup / tham chiếu formula: {"type", "value": [...]}
        v = v["value"]
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], (int, float)):
        v = v[0]
    if field_type in _DATE_TYPES and isinstance(v, (int, float)):
        t = dt.datetime.fromtimestamp(v / 1000, _VN_TZ)
        return t.strftime("%Y-%m-%d") if t.time() == dt.time() else t.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (bool, int, float)):
        return v
    if field_type == _NUMBER_TYPE and isinstance(v, str):  # đã thấy thật: field Number trả "33163"
        try:
            n = float(v)
            return int(n) if n.is_integer() else n
        except ValueError:
            return v
    return _text(v)


def fetch_table(token: str, url: str) -> dict[str, Any]:
    base, table, view = parse_url(url)
    params = {"view_id": view} if view else {}
    path = f"{base}/tables/{table}"
    fields = list(_paged(token, f"{path}/fields", params, limit=1000))
    types = {f["field_name"]: f["type"] for f in fields}
    rows = [
        {name: normalize_cell(item["fields"].get(name), ftype) for name, ftype in types.items()}
        for item in _paged(token, f"{path}/records", params, limit=MAX_ROWS)
    ]
    return {"columns": list(types), "rows": rows}


def check_access(sources: dict[str, str]) -> None:
    """Gọi thử API fields của từng bảng lúc lưu embed — báo lỗi quyền ngay cho người
    tạo, thay vì để người xem link Lark mới thấy dashboard trống."""
    token = get_token()
    for url in sources.values():
        base, table, view = parse_url(url)
        _get(token, f"{base}/tables/{table}/fields", {"page_size": 1, **({"view_id": view} if view else {})})
