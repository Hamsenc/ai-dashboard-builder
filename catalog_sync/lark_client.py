"""Client tối giản cho Lark Bitable REST API, dùng bởi catalog_sync để đọc
'02. Table Catalog' và '04. Business Logic - KPI'.

Khác với MCP tool `base_record_list` dùng trong phiên chat (chạy dưới danh tính
user, trả về format cột-mảng riêng của MCP) — job này chạy không người trực
(Cloud Scheduler), nên phải tự lấy tenant_access_token bằng app credentials
riêng của app (LARK_APP_ID/LARK_APP_SECRET), gọi thẳng REST API chuẩn của Lark,
và tự parse response theo đúng format items[].fields{} của Bitable API.

CHƯA CHẠY THỬ được với Lark thật trong phiên này — cần LARK_APP_ID/LARK_APP_SECRET
của 1 Lark app đã được cấp quyền đọc (bitable:app:readonly) trên base
AcITbzsvraObhisDdQXlO6tggkd. Test hiện tại của module này (tests/test_catalog_merge.py)
chỉ verify phần parse/normalize bằng fixture, không gọi mạng thật.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

import httpx

_RECORD_ID_RE = re.compile(r"rec[a-zA-Z0-9]{10,}")


class LarkAuthError(RuntimeError):
    pass


def get_tenant_access_token(host: str, app_id: str, app_secret: str) -> str:
    resp = httpx.post(
        f"{host}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise LarkAuthError(f"Không lấy được tenant_access_token: {data}")
    return data["tenant_access_token"]


def list_records(
    host: str,
    token: str,
    base_token: str,
    table_id: str,
    page_size: int = 100,
) -> Iterator[dict[str, Any]]:
    """Yield từng record thô dạng {'record_id': ..., 'fields': {...}} theo đúng
    format Lark Bitable API trả về (KHÔNG phải format của MCP base_record_list)."""
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        resp = httpx.get(
            f"{host}/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Lark API lỗi khi đọc table {table_id}: {payload}")

        data = payload["data"]
        for item in data.get("items", []):
            yield item

        if not data.get("has_more"):
            return
        page_token = data.get("page_token")


def field_text(value: Any) -> str:
    """Chuẩn hoá 1 giá trị field Lark (text/select/multi-select/...) về string
    người đọc được. Field select trong Bitable API có thể là string hoặc list
    tuỳ single/multi-select — xử lý dung hợp cả 2 thay vì giả định 1 dạng."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # field kiểu "link tới bảng khác" thường có 'text' hiển thị sẵn
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "text_arr" in item:
                    parts.extend(str(t) for t in item["text_arr"])
            else:
                parts.append(str(item))
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        if "text" in value:
            return str(value["text"])
        return str(value)
    return str(value)


def linked_record_ids(value: Any) -> list[str]:
    """Trích mọi record_id (dạng 'recXXXXXXXXXX') xuất hiện trong 1 giá trị field
    link-to-record, bất kể Lark trả đúng shape nào (record_ids/link_record_ids/id/...).
    Dùng regex trên toàn bộ chuỗi JSON-hoá thay vì bám 1 key cụ thể — bền hơn
    trước các đời API khác nhau, vì tiền tố 'rec' của Lark record id ổn định."""
    return _RECORD_ID_RE.findall(str(value))
