"""Xem/refresh/sửa 1 dashboard đã build. Refresh KHÔNG gọi LLM — chỉ chạy lại đúng
SQL đã lưu trong build hiện hành, đúng thiết kế trong plan.

Edit (chat để chỉnh sửa) tách 2 nhánh theo đúng luật "không âm thầm đổi KPI":
- cosmetic (is_structural_change=false): server TỰ áp dụng ngay (gọi thẳng
  apply_blueprint), không cần user bấm duyệt lại — vì không đổi số liệu.
- structural (is_structural_change=true, hoặc action clarify/refuse): trả y hệt
  response của chat, KHÔNG tự áp dụng — frontend phải hiện nút Duyệt (gọi
  /api/blueprint/approve) giống hệt luồng tạo dashboard mới."""

from __future__ import annotations

import datetime

from api.blueprint import ApplyResponse, apply_blueprint
from api.chat import ChatMessageRequest, ChatMessageResponse, get_bq_client, run_planner_turn
from auth.deps import get_current_user
from catalog.client import load_catalog
from execution import bq_client
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from storage import bq_store

router = APIRouter(prefix="/api/dashboard")


class EditResponse(BaseModel):
    chat: ChatMessageResponse
    applied: ApplyResponse | None = None


class FilterRequest(BaseModel):
    start_date: datetime.date
    end_date: datetime.date


@router.get("")
async def list_dashboards(user: str = Depends(get_current_user)):
    client = get_bq_client()
    dashboards = bq_store.list_my_dashboards(client, user)
    return {"dashboards": dashboards}


@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    blueprint = bq_store.get_current_blueprint(client, dashboard_id)
    if not blueprint:
        raise HTTPException(404, f"Không tìm thấy dashboard '{dashboard_id}'.")
    build_row = bq_store.get_current_build(client, dashboard_id)
    if not build_row:
        raise HTTPException(404, f"Dashboard '{dashboard_id}' chưa có build nào.")

    results = bq_client.run_queries_for_render(
        client, build_row["sql_per_kpi"],
        start_date=build_row.get("default_start_date"), end_date=build_row.get("default_end_date"),
    )
    return {
        "blueprint": blueprint, "results": results,
        "default_start_date": build_row.get("default_start_date"),
        "default_end_date": build_row.get("default_end_date"),
    }


@router.post("/{dashboard_id}/refresh")
async def refresh_dashboard(dashboard_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    build_row = bq_store.get_current_build(client, dashboard_id)
    if not build_row:
        raise HTTPException(404, f"Dashboard '{dashboard_id}' chưa có build nào.")
    results = bq_client.run_queries_for_render(
        client, build_row["sql_per_kpi"],
        start_date=build_row.get("default_start_date"), end_date=build_row.get("default_end_date"),
    )
    return {"results": results}


@router.post("/{dashboard_id}/filter")
async def filter_dashboard(dashboard_id: str, req: FilterRequest, user: str = Depends(get_current_user)):
    """Bộ lọc ngày sống — chạy lại ĐÚNG SQL đã duyệt/lưu với @start_date/@end_date
    khác, KHÔNG gọi LLM, KHÔNG ghi blueprint/build mới (chỉ đổi view tạm thời, giống
    Refresh — nếu SQL của 1 KPI không dùng @start_date/@end_date thì filter không ảnh
    hưởng KPI đó, không lỗi)."""
    if req.start_date > req.end_date:
        raise HTTPException(400, "start_date phải <= end_date.")
    client = get_bq_client()
    build_row = bq_store.get_current_build(client, dashboard_id)
    if not build_row:
        raise HTTPException(404, f"Dashboard '{dashboard_id}' chưa có build nào.")
    results = bq_client.run_queries_for_render(
        client, build_row["sql_per_kpi"], start_date=req.start_date, end_date=req.end_date,
    )
    return {"results": results}


@router.post("/{dashboard_id}/edit", response_model=EditResponse)
async def edit_dashboard(dashboard_id: str, req: ChatMessageRequest, user: str = Depends(get_current_user)):
    client = get_bq_client()
    existing = bq_store.get_current_blueprint(client, dashboard_id)
    if not existing:
        raise HTTPException(404, f"Không tìm thấy dashboard '{dashboard_id}' để chỉnh sửa.")

    chat_resp = await run_planner_turn(req.session_id, req.message, user, dashboard_id=dashboard_id)

    if chat_resp.action != "propose_blueprint" or chat_resp.is_structural_change or not chat_resp.blueprint:
        # clarify / refuse_out_of_scope / structural (bắt buộc user tự bấm Duyệt qua
        # /api/blueprint/approve, KHÔNG tự áp dụng ở đây) — trả nguyên response chat.
        return EditResponse(chat=chat_resp, applied=None)

    # Cosmetic: server tự áp dụng ngay, không chờ user bấm duyệt.
    catalog = load_catalog()
    applied = await apply_blueprint(
        client, dashboard_id, chat_resp.blueprint, catalog, user,
        parent_blueprint_id=existing["blueprint_id"],
        is_structural_change=False,
        change_summary=chat_resp.change_summary or None,
    )
    return EditResponse(chat=chat_resp, applied=applied)
