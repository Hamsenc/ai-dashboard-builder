"""API upload/list/revoke Dashboard Embeds — GATED bằng session Lark OAuth +
whitelist (Config.UPLOAD_WHITELIST_EMAILS). Route xem dashboard công khai nằm
riêng ở app/api/embed_view.py (KHÔNG có Depends(get_current_user) ở đó), vì
viewer qua link Lark không có session cookie."""

from __future__ import annotations

import json
import secrets

from api.catalog import get_bq_client
from api.embed_view import invalidate_cache
from auth.deps import get_current_user
from config import Config
from datasource import bq_meta
from embeds import query_spec
from embeds.gcs_store import upload_html
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from storage import embeds_store

router = APIRouter(prefix="/api/embeds")


def _is_whitelisted(user: str) -> bool:
    return user.strip().lower() in Config.UPLOAD_WHITELIST_EMAILS


def _validate_spec(client, spec_dict: dict | None) -> tuple[dict | None, str | None]:
    """Validate spec (nếu có) + trả về (các) table_id suy ra từ spec, dùng chung cho
    cả tạo mới lẫn sửa embed. Hỗ trợ cả spec 1 bảng cũ lẫn spec nhiều bảng mới
    ({"specs": {tên: spec, ...}}, xem query_spec.is_multi_spec). Raise HTTPException
    403/400 nếu spec sai."""
    if not spec_dict:
        return None, None
    try:
        if query_spec.is_multi_spec(spec_dict):
            plans = query_spec.build_queries(client, spec_dict)
            table_id = ", ".join(sorted({p.table_id for p in plans.values()}))
        else:
            plan = query_spec.build_query(client, spec_dict)
            table_id = plan.table_id
    except bq_meta.OutOfScopeError as e:
        raise HTTPException(403, str(e)) from e
    except query_spec.InvalidQuerySpecError as e:
        raise HTTPException(400, str(e)) from e
    return spec_dict, table_id


@router.get("")
def list_embeds(all: bool = False, user: str = Depends(get_current_user)):
    client = get_bq_client()
    # ?all=true chỉ tác dụng với whitelist (đóng vai "admin") — cần thấy embed của
    # người khác mới có đường revoke; whitelist nhỏ nên không cần UI phân trang.
    if all and _is_whitelisted(user):
        embeds = embeds_store.list_current_embeds(client)
    else:
        embeds = embeds_store.list_current_embeds(client, created_by=user)
    return {"embeds": embeds}


@router.post("")
async def create_embed(
    file: UploadFile,
    title: str = Form(...),
    data_query_spec: str | None = Form(default=None),
    user: str = Depends(get_current_user),
):
    if not _is_whitelisted(user):
        raise HTTPException(403, "Bạn chưa được cấp quyền upload dashboard — liên hệ admin để thêm vào whitelist.")

    if not file.filename or not file.filename.lower().endswith(".html"):
        raise HTTPException(400, "Chỉ chấp nhận file .html.")
    if file.size is not None and file.size > Config.EMBED_MAX_HTML_BYTES:
        raise HTTPException(413, f"File vượt quá giới hạn {Config.EMBED_MAX_HTML_BYTES:,} bytes.")

    raw = await file.read(Config.EMBED_MAX_HTML_BYTES + 1)
    if len(raw) > Config.EMBED_MAX_HTML_BYTES:
        raise HTTPException(413, f"File vượt quá giới hạn {Config.EMBED_MAX_HTML_BYTES:,} bytes.")
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(400, "File phải là văn bản UTF-8.") from e

    client = get_bq_client()

    spec_dict = None
    if data_query_spec:
        try:
            spec_dict = json.loads(data_query_spec)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"data_query_spec không phải JSON hợp lệ: {e}") from e
    # Chỉ để VALIDATE spec ngay lúc upload (bắt lỗi sớm) — SQL/QueryPlan build ra ở
    # đây không dùng, endpoint /d/{id}/data sẽ tự build lại từ spec đã lưu để luôn
    # theo schema/scope mới nhất.
    spec_dict, data_table_id = await run_in_threadpool(_validate_spec, client, spec_dict)

    embed_id = secrets.token_urlsafe(16)
    gcs_path = f"embeds/{embed_id}.html"

    await run_in_threadpool(upload_html, gcs_path, html)
    await run_in_threadpool(
        embeds_store.insert_embed_event,
        client, embed_id, "created",
        created_by=user, title=title, gcs_path=gcs_path,
        data_table_id=data_table_id, data_query_spec=spec_dict,
    )

    return {"embed_id": embed_id, "view_url": f"/d/{embed_id}"}


class UpdateEmbedRequest(BaseModel):
    title: str
    data_query_spec: dict | None = None


@router.post("/{embed_id}")
def update_embed(embed_id: str, req: UpdateEmbedRequest, user: str = Depends(get_current_user)):
    """Sửa tên/dữ liệu sống của embed đã tạo — KHÔNG đổi embed_id/link, KHÔNG đổi
    file HTML (muốn đổi nội dung file thì thu hồi rồi upload lại). Ghi thêm 1 event
    'updated' mang đủ mọi field (kể cả gcs_path giữ nguyên từ bản ghi hiện tại) —
    đúng quy ước append-only, "current" luôn là bản ghi mới nhất theo embed_id."""
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    if embed["created_by"].strip().lower() != user.strip().lower() and not _is_whitelisted(user):
        raise HTTPException(403, "Bạn không có quyền sửa embed này.")

    title = req.title.strip()
    if not title:
        raise HTTPException(400, "Tên dashboard không được để trống.")
    spec_dict, data_table_id = _validate_spec(client, req.data_query_spec)

    embeds_store.insert_embed_event(
        client, embed_id, "updated",
        created_by=user, title=title, gcs_path=embed["gcs_path"],
        data_table_id=data_table_id, data_query_spec=spec_dict,
    )
    invalidate_cache(embed_id)
    return {"embed_id": embed_id, "title": title, "data_query_spec": spec_dict}


@router.post("/{embed_id}/revoke")
def revoke_embed(embed_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    if embed["created_by"].strip().lower() != user.strip().lower() and not _is_whitelisted(user):
        raise HTTPException(403, "Bạn không có quyền thu hồi embed này.")

    embeds_store.insert_embed_event(client, embed_id, "revoked", created_by=user)
    return {"embed_id": embed_id, "status": "revoked"}
