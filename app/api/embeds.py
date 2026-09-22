"""API upload/list/revoke Dashboard Embeds — GATED bằng session Lark OAuth +
quyền embed (auth.roles.can_use_embeds: whitelist cũ + role 'embed'/'admin' cấp
qua /admin.html). Route xem dashboard công khai nằm riêng ở app/api/embed_view.py
(KHÔNG có Depends(get_current_user) ở đó), vì viewer qua link Lark không có
session cookie."""

from __future__ import annotations

import csv
import io
import json
import secrets

import openpyxl
from api.catalog import get_bq_client
from api.embed_view import invalidate_cache
from auth.deps import get_current_user
from auth.roles import can_use_embeds, is_admin
from config import Config
from datasource import bq_meta
from embeds import query_spec, template_gen
from embeds.gcs_store import upload_bytes, upload_html
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from storage import admin_store, embeds_store

router = APIRouter(prefix="/api/embeds")

_DATA_FILE_EXTENSIONS = (".xlsx", ".xls", ".csv")
_DATA_FILE_CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
}


def _is_owner(embed: dict, user: str) -> bool:
    return embed["owner_email"].strip().lower() == user.strip().lower()


def _assert_can_edit(client, embed: dict, user: str) -> None:
    """Dùng cho sửa metadata/spec + re-upload file dữ liệu — chủ sở hữu (owner_email,
    cố định từ lúc tạo, xem 018_v_current_dashboard_embeds_owner.sql), admin, hoặc
    người được share quyền 'edit' embed này mới được phép. KHÔNG dùng cho revoke (xem
    _assert_can_revoke) — share 'edit' chỉ sửa được thông tin, không thu hồi link."""
    if _is_owner(embed, user) or is_admin(user):
        return
    if embeds_store.get_share_permission(client, embed["embed_id"], user) == "edit":
        return
    raise HTTPException(403, "Bạn không có quyền sửa embed này.")


def _assert_can_revoke(embed: dict, user: str) -> None:
    """Chỉ chủ sở hữu hoặc admin mới thu hồi được link — share 'edit' không đủ, vì
    thu hồi phá link công khai đang chạy, ảnh hưởng mọi người đang xem."""
    if not _is_owner(embed, user) and not is_admin(user):
        raise HTTPException(403, "Chỉ chủ sở hữu hoặc admin mới thu hồi được link này.")


def _extract_file_columns(ext: str, raw: bytes) -> list[str] | None:
    """Đọc dòng header (tên cột) của file dữ liệu vừa upload, dùng để phát hiện đổi
    cột giữa 2 lần upload — xem update_embed_data_file(). Trả None nếu không parse
    được (file rỗng/hỏng, hoặc .xls — định dạng OLE nhị phân cũ, không có lib nào
    sẵn trong repo để đọc, bỏ qua check cho định dạng này).
    # ponytail: .xls không được check cột, thêm xlrd nếu sau này thực sự cần."""
    try:
        if ext == ".csv":
            text = raw.decode("utf-8-sig", errors="replace")
            header = next(csv.reader(io.StringIO(text)), None)
            return [c.strip() for c in header] if header else None
        if ext == ".xlsx":
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True)
            header = next(wb.active.iter_rows(min_row=1, max_row=1, values_only=True), None)
            return [str(c).strip() for c in header if c is not None] if header else None
    except Exception:
        return None
    return None


async def _read_and_store_data_file(embed_id: str, data_file: UploadFile) -> tuple[str, str, list[str] | None]:
    """Validate đuôi/kích thước, lưu lên GCS, trả về (gcs_path, original_filename, columns)."""
    name = data_file.filename or ""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in _DATA_FILE_EXTENSIONS:
        raise HTTPException(400, "File dữ liệu chỉ chấp nhận .xlsx, .xls hoặc .csv.")
    if data_file.size is not None and data_file.size > Config.EMBED_MAX_DATA_FILE_BYTES:
        raise HTTPException(413, f"File dữ liệu vượt quá giới hạn {Config.EMBED_MAX_DATA_FILE_BYTES:,} bytes.")

    raw = await data_file.read(Config.EMBED_MAX_DATA_FILE_BYTES + 1)
    if len(raw) > Config.EMBED_MAX_DATA_FILE_BYTES:
        raise HTTPException(413, f"File dữ liệu vượt quá giới hạn {Config.EMBED_MAX_DATA_FILE_BYTES:,} bytes.")

    gcs_path = f"embeds/{embed_id}/data-file"
    await run_in_threadpool(upload_bytes, gcs_path, raw, _DATA_FILE_CONTENT_TYPES[ext])
    columns = await run_in_threadpool(_extract_file_columns, ext, raw)
    return gcs_path, name, columns


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


def _add_schema_warnings(client, embeds: list[dict]) -> None:
    """Với mỗi embed dùng nguồn BigQuery sống, thử build lại query từ spec đã lưu —
    y hệt việc /d/{id}/data làm lúc viewer mở link (embed_view.py) — để phát hiện
    SỚM nếu bảng nguồn đã đổi/xoá cột kể từ lúc lưu spec, thay vì để chủ sở hữu chỉ
    biết khi có người báo dashboard lỗi. Tái dùng nguyên validate của query_spec,
    không viết lại logic so sánh cột."""
    for e in embeds:
        spec = e.get("data_query_spec")
        e["schema_warning"] = None
        if not spec:
            continue
        try:
            if query_spec.is_multi_spec(spec):
                query_spec.build_queries(client, spec)
            else:
                query_spec.build_query(client, spec)
        except (query_spec.InvalidQuerySpecError, bq_meta.OutOfScopeError) as ex:
            e["schema_warning"] = str(ex)


@router.get("")
def list_embeds(all: bool = False, user: str = Depends(get_current_user)):
    """Mặc định chỉ trả embed CỦA TÔI + embed được share cho tôi (riêng hoặc share
    '*' toàn nội bộ) — không còn thấy embed của người khác chỉ vì có quyền upload.
    ?all=true chỉ tác dụng với admin thật (is_admin) — xem toàn bộ để quản lý."""
    client = get_bq_client()
    if all and is_admin(user):
        embeds = embeds_store.list_current_embeds(client)
        for e in embeds:
            e["permission"] = "owner" if _is_owner(e, user) else "admin"
        _add_schema_warnings(client, embeds)
        return {"embeds": embeds}

    own = embeds_store.list_current_embeds(client, owner_email=user)
    for e in own:
        e["permission"] = "owner"

    shared_permissions = embeds_store.get_shared_permissions_for_user(client, user)
    shared_ids = [eid for eid in shared_permissions if eid not in {e["embed_id"] for e in own}]
    shared = embeds_store.list_current_embeds_by_ids(client, shared_ids)
    for e in shared:
        e["permission"] = shared_permissions[e["embed_id"]]

    embeds = sorted(own + shared, key=lambda e: e["event_at"], reverse=True)
    _add_schema_warnings(client, embeds)
    return {"embeds": embeds}


@router.post("/request-access")
def request_access(user: str = Depends(get_current_user)):
    """Tự phục vụ: user chưa có quyền embed bấm nút "Yêu cầu cấp quyền" ở
    embeds.html — ghi 1 event 'requested' vào user_roles, admin thấy trong tab
    Phân quyền của /admin.html để duyệt (grant) hoặc từ chối (revoke)."""
    if can_use_embeds(user):
        return {"status": "already_granted"}
    client = get_bq_client()
    existing = admin_store.get_latest_role_event(client, user, "embed")
    if existing and existing["event"] == "requested":
        return {"status": "already_requested"}
    admin_store.insert_role_event(client, user, "embed", "requested", granted_by=user)
    return {"status": "requested"}


@router.post("")
async def create_embed(
    file: UploadFile,
    title: str = Form(...),
    data_query_spec: str | None = Form(default=None),
    owner_name: str | None = Form(default=None),
    prompt_note: str | None = Form(default=None),
    group_name: str | None = Form(default=None),
    data_file: UploadFile | None = File(default=None),
    user: str = Depends(get_current_user),
):
    if not can_use_embeds(user):
        raise HTTPException(403, "Bạn chưa được cấp quyền upload dashboard — liên hệ admin để cấp quyền embed.")

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

    data_file_gcs_path = data_file_name = data_file_columns = None
    if data_file is not None and data_file.filename:
        data_file_gcs_path, data_file_name, data_file_columns = await _read_and_store_data_file(embed_id, data_file)

    await run_in_threadpool(upload_html, gcs_path, html)
    await run_in_threadpool(
        embeds_store.insert_embed_event,
        client, embed_id, "created",
        created_by=user, title=title, gcs_path=gcs_path,
        data_table_id=data_table_id, data_query_spec=spec_dict,
        owner_name=owner_name, prompt_note=prompt_note,
        data_file_gcs_path=data_file_gcs_path, data_file_name=data_file_name,
        group_name=(group_name or "").strip() or None,
        data_file_columns=data_file_columns,
    )

    return {"embed_id": embed_id, "view_url": f"/d/{embed_id}"}


class GenerateEmbedRequest(BaseModel):
    title: str
    data_query_spec: dict
    widgets: list[dict]
    owner_name: str | None = None
    prompt_note: str | None = None
    group_name: str | None = None


@router.post("/generate")
def generate_embed(req: GenerateEmbedRequest, user: str = Depends(get_current_user)):
    """Tạo embed KHÔNG cần tự viết HTML — server tự lắp dashboard từ 1 data_query_spec
    (bảng BigQuery + cột/tổng hợp, y hệt spec dùng cho 'dữ liệu sống' thường) và danh
    sách widget (KPI/Bar/Line/Table, xem embeds/template_gen.py). Chỉ hỗ trợ 1 bảng
    (không phải {"specs": {...}}) — cần nhiều bảng thì dùng chế độ Upload HTML."""
    if not can_use_embeds(user):
        raise HTTPException(403, "Bạn chưa được cấp quyền upload dashboard — liên hệ admin để cấp quyền embed.")

    title = req.title.strip()
    if not title:
        raise HTTPException(400, "Tên dashboard không được để trống.")

    client = get_bq_client()
    if query_spec.is_multi_spec(req.data_query_spec):
        raise HTTPException(400, "Dashboard mẫu chỉ hỗ trợ 1 bảng dữ liệu — dùng chế độ Upload file HTML nếu cần nhiều bảng.")
    spec_dict, data_table_id = _validate_spec(client, req.data_query_spec)
    if spec_dict is None:
        raise HTTPException(400, "Cần chọn 1 nguồn dữ liệu BigQuery cho dashboard mẫu.")

    available_fields = set(spec_dict.get("columns") or []) | {a["alias"] for a in (spec_dict.get("aggregations") or [])}
    try:
        template_gen.validate_widgets(req.widgets, available_fields)
    except template_gen.InvalidWidgetError as e:
        raise HTTPException(400, str(e)) from e

    html = template_gen.render_dashboard_html(title, req.widgets)

    embed_id = secrets.token_urlsafe(16)
    gcs_path = f"embeds/{embed_id}.html"
    upload_html(gcs_path, html)
    embeds_store.insert_embed_event(
        client, embed_id, "created",
        created_by=user, title=title, gcs_path=gcs_path,
        data_table_id=data_table_id, data_query_spec=spec_dict,
        owner_name=req.owner_name, prompt_note=req.prompt_note,
        group_name=(req.group_name or "").strip() or None,
    )
    return {"embed_id": embed_id, "view_url": f"/d/{embed_id}"}


class UpdateEmbedRequest(BaseModel):
    title: str
    data_query_spec: dict | None = None
    owner_name: str | None = None
    prompt_note: str | None = None
    group_name: str | None = None


@router.post("/{embed_id}")
def update_embed(embed_id: str, req: UpdateEmbedRequest, user: str = Depends(get_current_user)):
    """Sửa tên/dữ liệu sống của embed đã tạo — KHÔNG đổi embed_id/link, KHÔNG đổi
    file HTML (muốn đổi nội dung file thì thu hồi rồi upload lại). Ghi thêm 1 event
    'updated' mang đủ mọi field (kể cả gcs_path/data_file_* giữ nguyên từ bản ghi hiện
    tại) — đúng quy ước append-only, "current" luôn là bản ghi mới nhất theo embed_id."""
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    _assert_can_edit(client, embed, user)

    title = req.title.strip()
    if not title:
        raise HTTPException(400, "Tên dashboard không được để trống.")
    spec_dict, data_table_id = _validate_spec(client, req.data_query_spec)

    embeds_store.insert_embed_event(
        client, embed_id, "updated",
        created_by=user, title=title, gcs_path=embed["gcs_path"],
        data_table_id=data_table_id, data_query_spec=spec_dict,
        owner_name=req.owner_name, prompt_note=req.prompt_note,
        data_file_gcs_path=embed.get("data_file_gcs_path"), data_file_name=embed.get("data_file_name"),
        group_name=(req.group_name or "").strip() or None,
        data_file_columns=embed.get("data_file_columns"),
    )
    invalidate_cache(embed_id)
    return {"embed_id": embed_id, "title": title, "data_query_spec": spec_dict}


@router.post("/{embed_id}/data-file")
async def update_embed_data_file(embed_id: str, data_file: UploadFile, user: str = Depends(get_current_user)):
    """Re-upload RIÊNG file dữ liệu (Excel/CSV) của 1 embed đã tạo — không đổi HTML/link,
    không đụng title/data_query_spec. Endpoint tách khỏi update_embed() vì đó nhận JSON,
    không mang được file."""
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    _assert_can_edit(client, embed, user)

    data_file_gcs_path, data_file_name, data_file_columns = await _read_and_store_data_file(embed_id, data_file)

    column_warning = None
    prev_columns = embed.get("data_file_columns")
    if prev_columns and data_file_columns:
        added = sorted(set(data_file_columns) - set(prev_columns))
        removed = sorted(set(prev_columns) - set(data_file_columns))
        if added or removed:
            parts = []
            if added:
                parts.append(f"thêm {added}")
            if removed:
                parts.append(f"bớt {removed}")
            column_warning = (
                f"Cột trong file mới khác file cũ: {', '.join(parts)}. "
                "Dashboard có thể hiển thị sai/thiếu nếu HTML đang tham chiếu cột cũ."
            )

    embeds_store.insert_embed_event(
        client, embed_id, "updated",
        created_by=user, title=embed["title"], gcs_path=embed["gcs_path"],
        data_table_id=embed.get("data_table_id"), data_query_spec=embed.get("data_query_spec"),
        owner_name=embed.get("owner_name"), prompt_note=embed.get("prompt_note"),
        data_file_gcs_path=data_file_gcs_path, data_file_name=data_file_name,
        group_name=embed.get("group_name"),
        data_file_columns=data_file_columns or prev_columns,
    )
    invalidate_cache(embed_id)
    return {"embed_id": embed_id, "data_file_name": data_file_name, "column_warning": column_warning}


@router.post("/{embed_id}/revoke")
def revoke_embed(embed_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    _assert_can_revoke(embed, user)

    embeds_store.insert_embed_event(client, embed_id, "revoked", created_by=user)
    return {"embed_id": embed_id, "status": "revoked"}


class ShareEmbedRequest(BaseModel):
    shared_with: str  # email cụ thể, hoặc '*' = chia sẻ cho tất cả user nội bộ
    permission: str  # 'view' | 'edit'


class UnshareEmbedRequest(BaseModel):
    shared_with: str


def _assert_can_manage_shares(embed: dict, user: str) -> None:
    """Chỉ chủ sở hữu hoặc admin mới thêm/gỡ share được — người được share quyền
    'edit' sửa được nội dung dashboard nhưng không được tự ý mời thêm người khác."""
    if not _is_owner(embed, user) and not is_admin(user):
        raise HTTPException(403, "Chỉ chủ sở hữu hoặc admin mới quản lý chia sẻ được.")


@router.get("/{embed_id}/shares")
def get_shares(embed_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    _assert_can_manage_shares(embed, user)
    return {"shares": embeds_store.list_shares_for_embed(client, embed_id)}


@router.post("/{embed_id}/shares")
def share_embed(embed_id: str, req: ShareEmbedRequest, user: str = Depends(get_current_user)):
    if req.permission not in ("view", "edit"):
        raise HTTPException(400, "permission phải là 'view' hoặc 'edit'.")
    shared_with = req.shared_with.strip().lower()
    if not shared_with:
        raise HTTPException(400, "Thiếu email hoặc '*' để chia sẻ.")
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    _assert_can_manage_shares(embed, user)
    if shared_with != "*" and shared_with == embed["owner_email"].strip().lower():
        raise HTTPException(400, "Không cần chia sẻ cho chính chủ sở hữu.")

    embeds_store.insert_share_event(client, embed_id, shared_with, req.permission, "shared", shared_by=user)
    return {"embed_id": embed_id, "shared_with": shared_with, "permission": req.permission}


@router.post("/{embed_id}/unshare")
def unshare_embed(embed_id: str, req: UnshareEmbedRequest, user: str = Depends(get_current_user)):
    client = get_bq_client()
    embed = embeds_store.get_current_embed(client, embed_id)
    if embed is None or embed["event"] == "revoked":
        raise HTTPException(404, "Không tìm thấy embed, hoặc đã bị thu hồi trước đó.")
    _assert_can_manage_shares(embed, user)

    embeds_store.insert_share_event(client, embed_id, req.shared_with, "view", "unshared", shared_by=user)
    return {"embed_id": embed_id, "status": "unshared"}
