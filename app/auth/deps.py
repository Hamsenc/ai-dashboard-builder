"""Dependency FastAPI cho 'current user'. Ưu tiên session cookie thật (Lark OAuth,
Phase 9). Fallback X-Dev-User CHỈ hoạt động khi env ALLOW_DEV_USER_HEADER=true — mặc
định TẮT. Từ khi Cloud Run chuyển sang public ở tầng mạng (--allow-unauthenticated,
bắt buộc để Lark OAuth redirect chạm được /auth/lark/callback), header này là cửa hậu
cho phép BẤT KỲ AI tự khai identity nếu không khoá — deploy.sh KHÔNG được set biến
này, để mặc định tắt trên production. Chỉ bật tay trong .env cục bộ khi dev/test."""

from __future__ import annotations

import os

from auth.session import verify_session_token
from config import Config
from fastapi import Header, HTTPException, Request


def get_current_user(request: Request, x_dev_user: str | None = Header(default=None)) -> str:
    session_cookie = request.cookies.get("session")
    if session_cookie:
        info = verify_session_token(session_cookie)
        if info:
            return info.get("email") or info.get("lark_user_id") or Config.DEV_USER_FALLBACK

    if os.environ.get("ALLOW_DEV_USER_HEADER") == "true":
        return x_dev_user or Config.DEV_USER_FALLBACK

    raise HTTPException(401, "Chưa đăng nhập — vào /auth/lark/login để đăng nhập bằng Lark.")
