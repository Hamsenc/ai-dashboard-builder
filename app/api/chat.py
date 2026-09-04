"""API chat: 1 lượt = 1 request/response JSON (KHÔNG streaming — cắt bớt SSE khỏi
scope MVP để có 1 walking skeleton chạy được sớm; nâng cấp lên SSE sau nếu cần,
không đổi hợp đồng response bên dưới, chỉ đổi cách truyền tải).

`run_planner_turn` dùng chung cho cả tạo dashboard mới (POST /message, dashboard_id=
None) lẫn chỉnh sửa dashboard có sẵn (dashboard.py gọi lại với dashboard_id thật để
Planner biết current_blueprint mà so sánh cosmetic/structural)."""

from __future__ import annotations

import uuid
from typing import Any

from auth.deps import get_current_user
from catalog.client import load_catalog
from fastapi import APIRouter, Depends
from google.cloud import bigquery
from planner.blueprint_schema import PlannerTurn
from planner.service import ChatTurn, next_turn
from pydantic import BaseModel
from storage import bq_store

router = APIRouter(prefix="/api/chat")

# State hội thoại đang chạy giữ in-process (không phải hot-path của BigQuery) — xem
# lý do trong DDL comment 004_chat_messages.sql. Mất khi restart instance — chấp
# nhận được ở quy mô nội bộ công ty cho MVP.
_sessions: dict[str, dict[str, Any]] = {}


class ChatMessageRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatMessageResponse(BaseModel):
    session_id: str
    action: str
    message_to_user: str
    blueprint: dict | None = None
    clarifying_options: list[dict] = []
    is_structural_change: bool = False
    change_summary: str = ""


def get_bq_client() -> bigquery.Client:
    return bigquery.Client()


async def run_planner_turn(
    session_id: str | None,
    message: str,
    user: str,
    dashboard_id: str | None = None,
) -> ChatMessageResponse:
    session_id = session_id or str(uuid.uuid4())
    session = _sessions.setdefault(session_id, {"history": [], "last_turn": None})

    session["history"].append(ChatTurn("user", message))

    client = get_bq_client()
    bq_store.insert_chat_message(
        client, session_id=session_id, turn_index=len(session["history"]) - 1,
        role="user", content=message, created_by=user, dashboard_id=dashboard_id,
    )

    catalog = load_catalog()
    current_blueprint = None
    if dashboard_id:
        existing = bq_store.get_current_blueprint(client, dashboard_id)
        current_blueprint = existing["spec"] if existing else None

    turn: PlannerTurn = await next_turn(catalog, session["history"], current_blueprint=current_blueprint)

    session["history"].append(ChatTurn("planner", turn.message_to_user))
    session["last_turn"] = turn
    session["dashboard_id"] = dashboard_id

    bq_store.insert_chat_message(
        client, session_id=session_id, turn_index=len(session["history"]) - 1,
        role="planner", content=turn.message_to_user, created_by=user, dashboard_id=dashboard_id,
        structured_payload={"action": turn.action, "is_structural_change": turn.is_structural_change},
    )

    return ChatMessageResponse(
        session_id=session_id,
        action=turn.action,
        message_to_user=turn.message_to_user,
        blueprint=turn.blueprint.model_dump() if turn.blueprint else None,
        clarifying_options=[o.model_dump() for o in turn.clarifying_options],
        is_structural_change=turn.is_structural_change,
        change_summary=turn.change_summary,
    )


@router.post("/message", response_model=ChatMessageResponse)
async def post_message(req: ChatMessageRequest, user: str = Depends(get_current_user)):
    return await run_planner_turn(req.session_id, req.message, user, dashboard_id=None)


def get_session(session_id: str) -> dict[str, Any] | None:
    return _sessions.get(session_id)
