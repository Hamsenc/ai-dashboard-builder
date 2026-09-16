"""API upload/list/revoke Dashboard Embeds — GATED bằng session Lark OAuth +
whitelist (Config.UPLOAD_WHITELIST_EMAILS). Route xem dashboard công khai nằm
riêng ở app/api/embed_view.py (KHÔNG có Depends(get_current_user) ở đó), vì
viewer qua link Lark không có session cookie."""

from __future__ import annotations

import json
import secrets

from api.catalog import get_bq_client
from auth.deps import get_current_user
from config import Config
from datasource import bq_meta
from embeds import query_spec
from embeds.gcs_store import upload_html
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from storage import embeds_store

router = APIRouter(prefix="/api/embeds")


def _is_whitelisted(user: str) -> bool:
    return user.strip().lower() in Config.UPLOAD_WHITELIST_EMAILS


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
    data_table_id = None
    if data_query_spec:
        try:
            spec_dict = json.loads(data_query_spec)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"data_query_spec không phải JSON hợp lệ: {e}") from e
        try:
            # Chỉ để VALIDATE spec ngay lúc upload (bắt lỗi sớm cho người upload) —
            # SQL/QueryPlan build ra ở đây không dùng, endpoint /d/{id}/data sẽ tự
            # build lại từ spec đã lưu để luôn theo schema/scope mới nhất.
            plan = await run_in_threadpool(query_spec.build_query, client, spec_dict)
        except bq_meta.OutOfScopeError as e:
            raise HTTPException(403, str(e)) from e
        except query_spec.InvalidQuerySpecError as e:
            raise HTTPException(400, str(e)) from e
        data_table_id = plan.table_id

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


@router.post("/{embed_id}/revoke")
def revoke_embed(embed_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] != "created":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    if embed["created_by"].strip().lower() != user.strip().lower() and not _is_whitelisted(user):
        raise HTTPException(403, "Bạn không có quyền thu hồi embed này.")

    embeds_store.insert_embed_event(client, embed_id, "revoked", created_by=user)
    return {"embed_id": embed_id, "status": "revoked"}
