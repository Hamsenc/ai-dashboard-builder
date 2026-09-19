"""Quyền admin/embed — SUPER_ADMIN_EMAILS (Config, env) luôn có cả 2 role; người
khác được cấp qua bảng raw_dashboard_builder_user_roles (xem storage/admin_store.py),
quản lý ở trang /admin.html. can_use_embeds() giữ tương thích ngược với
UPLOAD_WHITELIST_EMAILS cũ (env) — ai đang được whitelist trước đây không bị mất
quyền khi tính năng này ra mắt."""

from __future__ import annotations

from api.catalog import get_bq_client
from auth.deps import get_current_user
from config import Config
from fastapi import Depends, HTTPException
from storage import admin_store


def is_super_admin(email: str) -> bool:
    return email.strip().lower() in Config.SUPER_ADMIN_EMAILS


def has_role(email: str, role: str) -> bool:
    if is_super_admin(email):
        return True
    return role in admin_store.get_active_roles(get_bq_client(), email)


def can_use_embeds(email: str) -> bool:
    return email.strip().lower() in Config.UPLOAD_WHITELIST_EMAILS or has_role(email, "embed") or has_role(email, "admin")


def is_admin(email: str) -> bool:
    return has_role(email, "admin")


def require_admin(user: str = Depends(get_current_user)) -> str:
    if not is_admin(user):
        raise HTTPException(403, "Bạn không có quyền admin.")
    return user
