"""Ký/xác minh session cookie bằng SESSION_SECRET (Secret Manager). Cookie tự chứa
danh tính (không cần lưu session server-side) — hết hạn sau 12h, buộc đăng nhập lại
định kỳ thay vì giữ refresh token của Lark (app chỉ cần danh tính, không cần quyền
truy cập API Lark thay mặt user — sync job đã tự xác thực bằng app credentials riêng)."""

from __future__ import annotations

import os
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_MAX_AGE_SECONDS = 12 * 60 * 60


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ["SESSION_SECRET"]
    return URLSafeTimedSerializer(secret, salt="dashboard-builder-session")


def create_session_token(user_info: dict[str, Any]) -> str:
    return _serializer().dumps(user_info)


def verify_session_token(token: str) -> dict[str, Any] | None:
    try:
        return _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
