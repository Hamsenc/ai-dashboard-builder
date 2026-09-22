"""Trang quản trị (/admin.html) — GATED bằng auth.roles.require_admin. Theo dõi ai
đăng nhập + lịch sử nhúng dashboard, quản lý active link (revoke thay chủ sở hữu),
và cấp/thu hồi role 'admin'/'embed' cho người khác. Role 'admin' chỉ SUPER_ADMIN_EMAILS
(Config, xem auth/roles.py) mới cấp/thu hồi được cho người khác — role 'embed' thì
admin thường cũng cấp được."""

from __future__ import annotations

from api.catalog import get_bq_client
from api.embed_view import invalidate_cache
from auth.deps import get_current_user
from auth.roles import is_super_admin, require_admin
from config import Config
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from storage import admin_store, embeds_store

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

_ROLES = ("admin", "embed")


@router.get("/logins")
def list_logins(limit: int = 300):
    return {"logins": admin_store.list_logins(get_bq_client(), limit=limit)}


@router.get("/embed-events")
def list_embed_events(limit: int = 500):
    return {"events": embeds_store.list_embed_events(get_bq_client(), limit=limit)}


@router.get("/embeds")
def list_all_embeds():
    return {"embeds": embeds_store.list_current_embeds(get_bq_client())}


@router.get("/table-usage")
def table_usage(days: int = 30):
    return {"days": days, **admin_store.list_table_usage_summary(get_bq_client(), days=days)}


@router.post("/embeds/{embed_id}/revoke")
def revoke_any_embed(embed_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    embed = embeds_store.get_active_embed(client, embed_id)
    if embed is None:
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    embeds_store.insert_embed_event(client, embed_id, "revoked", created_by=user)
    invalidate_cache(embed_id)
    return {"embed_id": embed_id, "status": "revoked"}


@router.get("/roles")
def list_roles():
    client = get_bq_client()
    return {
        "super_admins": Config.SUPER_ADMIN_EMAILS,
        "roles": admin_store.list_current_roles(client),
        "pending_requests": admin_store.list_pending_role_requests(client),
    }


class RoleRequest(BaseModel):
    user_email: str
    role: str
    action: str  # 'grant' | 'revoke'


@router.post("/roles")
def set_role(req: RoleRequest, user: str = Depends(get_current_user)):
    if req.role not in _ROLES:
        raise HTTPException(400, f"Role không hợp lệ, chỉ nhận {_ROLES}.")
    if req.action not in ("grant", "revoke"):
        raise HTTPException(400, "Action không hợp lệ, chỉ nhận 'grant' hoặc 'revoke'.")
    if req.role == "admin" and not is_super_admin(user):
        raise HTTPException(403, "Chỉ quản lý cao nhất mới được cấp/thu hồi quyền admin.")
    if is_super_admin(req.user_email):
        raise HTTPException(400, "Người này đã là quản lý cao nhất, không cần/không thể đổi quyền.")

    event = "granted" if req.action == "grant" else "revoked"
    admin_store.insert_role_event(get_bq_client(), req.user_email, req.role, event, granted_by=user)
    return {"user_email": req.user_email.strip().lower(), "role": req.role, "event": event}
