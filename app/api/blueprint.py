"""Duyệt blueprint đã Planner đề xuất -> Build thật -> chạy thật -> trả kết quả để
render ngay (MVP: render trực tiếp trên trang chat, không có bước xem trước riêng).

`apply_blueprint` là logic dùng chung — approve() gọi cho dashboard mới HOẶC chỉnh
sửa structural (user bấm nút duyệt); dashboard.py gọi lại y hệt cho chỉnh sửa cosmetic
(tự động áp dụng, không cần user bấm duyệt lại) — cùng 1 đường ghi BigQuery, không
tách 2 code path dễ lệch nhau."""

from __future__ import annotations

from typing import Any

from api.chat import get_bq_client, get_session
from auth.deps import get_current_user
from builder.service import build
from catalog.client import load_catalog
from execution import bq_client
from fastapi import APIRouter, Depends, HTTPException
from google.cloud import bigquery
from pydantic import BaseModel
from storage import bq_store

router = APIRouter(prefix="/api/blueprint")


class ApproveRequest(BaseModel):
    session_id: str
    dashboard_id: str


class ApplyResponse(BaseModel):
    dashboard_id: str
    blueprint_id: str
    build_id: str
    default_start_date: str
    default_end_date: str
    results: list[dict[str, Any]]


async def apply_blueprint(
    client: bigquery.Client,
    dashboard_id: str,
    blueprint_dict: dict[str, Any],
    catalog: dict[str, Any],
    user: str,
    parent_blueprint_id: str | None = None,
    is_structural_change: bool | None = None,
    change_summary: str | None = None,
) -> ApplyResponse:
    bp_row = bq_store.insert_approved_blueprint(
        client, dashboard_id=dashboard_id, spec=blueprint_dict,
        catalog_version_used=catalog["generated_at"], created_by=user,
        parent_blueprint_id=parent_blueprint_id,
        is_structural_change=is_structural_change,
        change_summary=change_summary,
    )

    for kpi in blueprint_dict["kpis"]:
        if kpi["status"] == "Draft":
            bq_store.insert_kpi_confirmation(
                client, blueprint_id=bp_row["blueprint_id"], dashboard_id=dashboard_id,
                kpi_name=kpi["name"], kpi_status_at_confirmation="Draft",
                kpi_formula_text=kpi["definition"], catalog_version_used=catalog["generated_at"],
                confirmed_by=user, action="initial_confirm",
            )

    build_result = await build(blueprint_dict, catalog)
    sql_per_kpi = [q.model_dump() for q in build_result.queries]
    build_row = bq_store.insert_build(
        client, blueprint_id=bp_row["blueprint_id"], dashboard_id=dashboard_id,
        sql_per_kpi=sql_per_kpi, validator_status="passed",
        validator_report=build_result.validator_report,
        catalog_version_used=catalog["generated_at"], created_by=user,
        default_start_date=build_result.default_start_date,
        default_end_date=build_result.default_end_date,
    )

    results = bq_client.run_queries_for_render(
        client, sql_per_kpi,
        start_date=build_result.default_start_date, end_date=build_result.default_end_date,
    )

    return ApplyResponse(
        dashboard_id=dashboard_id,
        blueprint_id=bp_row["blueprint_id"],
        build_id=build_row["build_id"],
        default_start_date=build_result.default_start_date,
        default_end_date=build_result.default_end_date,
        results=results,
    )


@router.post("/approve", response_model=ApplyResponse)
async def approve(req: ApproveRequest, user: str = Depends(get_current_user)):
    session = get_session(req.session_id)
    if not session or not session.get("last_turn"):
        raise HTTPException(400, "Không có blueprint nào đang chờ duyệt trong session này.")

    turn = session["last_turn"]
    if turn.action != "propose_blueprint" or not turn.blueprint:
        raise HTTPException(400, f"Lượt gần nhất không phải đề xuất blueprint (action={turn.action}).")

    catalog = load_catalog()
    client = get_bq_client()

    existing = bq_store.get_current_blueprint(client, req.dashboard_id)
    parent_blueprint_id = existing["blueprint_id"] if existing else None

    return await apply_blueprint(
        client, req.dashboard_id, turn.blueprint.model_dump(), catalog, user,
        parent_blueprint_id=parent_blueprint_id,
        is_structural_change=turn.is_structural_change if existing else None,
        change_summary=turn.change_summary or None,
    )
