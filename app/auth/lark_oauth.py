"""Đăng nhập qua Lark OAuth2 — thay `X-Dev-User` header tạm bằng danh tính thật, để
mọi field audit (created_by/approved_by/confirmed_by) gắn đúng người dùng thật.

⚠️ CHƯA VERIFY được end-to-end trong phiên build này — khác mọi phần khác của app
(đều test được bằng script/curl), OAuth login cần 1 người thật bấm qua trình duyệt để
đăng nhập/chấp thuận trên Lark, không có cách tự động hoá việc đó an toàn. Endpoint
bên dưới viết theo đúng hiểu biết về Lark OAuth2 (authorization code flow, host quốc
tế larksuite.com — đã CÓ CƠ SỞ tin cậy vì `catalog_sync` đã xác thực thành công qua
LARK_OAUTH_HOST=https://open.larksuite.com để lấy tenant_access_token + đọc Base
thật, nên tenant này chắc chắn là Lark quốc tế chứ không phải Feishu). Nhưng phần
`/authen/v1/access_token` (đổi code lấy user token) có 2 phiên bản trong lịch sử API
của Lark (v1 cần app_access_token làm Bearer, v2 dùng client_id/secret trực tiếp
kiểu OAuth2 chuẩn) — code này dùng v2. TRƯỚC KHI DÙNG THẬT: bấm thử full flow 1 lần
sau khi deploy, và nếu endpoint sai, đối chiếu lại https://open.larksuite.com/document
(mục Authentication > User access token) để sửa đúng path.

Cần đăng ký `redirect_uri` (VD https://<service-url>/auth/lark/callback) trong Lark
Developer Console cho app đang dùng (LARK_APP_ID hiện có) — nếu chưa đăng ký, Lark sẽ
báo lỗi redirect_uri không hợp lệ ngay ở bước đầu."""

from __future__ import annotations

import os
import secrets

import httpx
from api.catalog import get_bq_client
from auth.session import create_session_token
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from storage import admin_store

router = APIRouter(prefix="/auth/lark")

_ACCOUNTS_HOST = "https://accounts.larksuite.com"  # trang consent, KHÁC host gọi API (open.larksuite.com)

# CSRF state — lưu in-process (đủ dùng cho MVP, single instance; nếu scale nhiều
# instance sau này cần chuyển sang cookie-based state thay vì dict server-side).
_pending_states: set[str] = set()


@router.get("/login")
async def login(request: Request):
    state = secrets.token_urlsafe(24)
    _pending_states.add(state)

    app_id = os.environ["LARK_APP_ID"]
    redirect_uri = str(request.url_for("lark_callback"))

    params = {
        "app_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    query = str(httpx.QueryParams(params))
    return RedirectResponse(f"{_ACCOUNTS_HOST}/open-apis/authen/v1/index?{query}")


@router.get("/callback", name="lark_callback")
async def callback(request: Request, code: str | None = None, state: str | None = None):
    if not code or not state or state not in _pending_states:
        raise HTTPException(400, "Thiếu code/state hoặc state không hợp lệ (có thể do phiên hết hạn).")
    _pending_states.discard(state)

    lark_host = os.environ["LARK_OAUTH_HOST"]
    app_id = os.environ["LARK_APP_ID"]
    app_secret = os.environ["LARK_APP_SECRET"]
    redirect_uri = str(request.url_for("lark_callback"))

    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            f"{lark_host}/open-apis/authen/v2/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        token_data = token_resp.json()
        if token_resp.status_code != 200 or "access_token" not in token_data:
            raise HTTPException(502, f"Lark đổi code thất bại: {token_data}")

        user_resp = await client.get(
            f"{lark_host}/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        user_data = user_resp.json()
        if user_data.get("code") != 0:
            raise HTTPException(502, f"Lark trả user_info lỗi: {user_data}")

    info = user_data["data"]
    session_payload = {
        "lark_user_id": info.get("open_id") or info.get("union_id"),
        # Ưu tiên enterprise_email (email công ty, gắn với tenant Lark) TRƯỚC email
        # cá nhân — mọi thứ dùng "user" để phân quyền (UPLOAD_WHITELIST_EMAILS,
        # audit trail) đều theo định danh email công ty. Thứ tự ngược lại (email
        # cá nhân trước) từng khiến 1 tài khoản có email cá nhân Gmail đăng nhập
        # được nhưng không khớp whitelist dù đúng người.
        "email": info.get("enterprise_email") or info.get("email") or "",
        "name": info.get("name", ""),
    }
    session_token = create_session_token(session_payload)

    try:
        await run_in_threadpool(
            admin_store.insert_login,
            get_bq_client(), session_payload["email"], session_payload["name"], session_payload["lark_user_id"],
        )
    except Exception as e:  # noqa: BLE001 — không chặn đăng nhập nếu ghi log lỗi
        print(f"CẢNH BÁO: ghi login log thất bại: {e}")

    response = RedirectResponse("/")
    # path="/api": mọi route có Depends(get_current_user) đều nằm dưới /api/*
    # (verify: app/main.py, app/api/catalog.py, app/api/advise.py) — giới hạn
    # cookie vào đúng path này để KHÔNG bị browser tự động gửi tới /d/{embed_id}
    # (Dashboard Embeds, xem app/api/embed_view.py). Cần thiết vì dashboard HTML
    # được phép chạy script sống — nếu cookie vẫn Path=/ mặc định, 1 script trong
    # dashboard (vô ý hay bị compromise) có thể fetch('/api/tables') và browser sẽ
    # tự đính kèm cookie của người đang xem nếu họ từng đăng nhập app này cùng
    # trình duyệt.
    response.set_cookie(
        "session", session_token, httponly=True, secure=True, samesite="lax",
        max_age=12 * 60 * 60, path="/api",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/")
    # path="/api" PHẢI khớp chính xác với path lúc set_cookie ở trên — cookie xoá
    # theo cặp (name, path), lệch path thì lệnh xoá này thành no-op, không xoá được
    # cookie thật.
    response.delete_cookie("session", path="/api")
    return response
