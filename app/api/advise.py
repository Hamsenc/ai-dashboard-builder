"""API tư vấn chọn bảng: 1 lượt = 1 request/response JSON (không streaming, cùng
quyết định MVP với chat.py cũ). Session hội thoại giữ in-process, mất khi restart
instance — chấp nhận được ở quy mô nội bộ công ty."""

from __future__ import annotations

import uuid
from typing import Any

from advisor.schema import AdvisorTurn
from advisor.service import ChatTurn, next_turn
from auth.deps import get_current_user
from datasource import bq_meta
from fastapi import APIRouter, Depends, HTTPException
from google.cloud import bigquery
from pydantic import BaseModel
from storage import bq_store

import llm_client

router = APIRouter(prefix="/api/advise")

_sessions: dict[str, dict[str, Any]] = {}


class AdviseMessageRequest(BaseModel):
    session_id: str | None = None
    message: str


class AdviseMessageResponse(BaseModel):
    session_id: str
    action: str
    message_to_user: str
    recommendations: list[dict] = []
    unsuitable: list[dict] = []
    missing_data: str = ""
    clarifying_options: list[dict] = []


def get_bq_client() -> bigquery.Client:
    return bigquery.Client()


@router.post("/message", response_model=AdviseMessageResponse)
async def post_message(req: AdviseMessageRequest, user: str = Depends(get_current_user)):
    session_id = req.session_id or str(uuid.uuid4())
    session = _sessions.setdefault(session_id, {"history": []})

    session["history"].append(ChatTurn("user", req.message))

    client = get_bq_client()
    bq_store.insert_chat_message(
        client, session_id=session_id, turn_index=len(session["history"]) - 1,
        role="user", content=req.message, created_by=user,
    )

    tables = bq_meta.list_tables(client)
    try:
        turn: AdvisorTurn = await next_turn(tables, session["history"])
    except llm_client.LLMError as e:
        # Rollback lượt user vừa thêm vào history in-process — nếu không, lần gửi
        # lại sau sẽ nhét 2 lượt "user" liên tiếp, next_turn() sẽ reject vì lịch sử
        # phải kết thúc đúng 1 lượt user (xem advisor/service.py).
        session["history"].pop()
        raise HTTPException(
            503, f"Trợ lý AI đang gặp sự cố, thử lại sau ít phút. Chi tiết: {e}"
        ) from e

    session["history"].append(ChatTurn("advisor", turn.message_to_user))

    bq_store.insert_chat_message(
        client, session_id=session_id, turn_index=len(session["history"]) - 1,
        role="advisor", content=turn.message_to_user, created_by=user,
        structured_payload={"action": turn.action},
    )

    return AdviseMessageResponse(
        session_id=session_id,
        action=turn.action,
        message_to_user=turn.message_to_user,
        recommendations=[r.model_dump() for r in turn.recommendations],
        unsuitable=[u.model_dump() for u in turn.unsuitable],
        missing_data=turn.missing_data,
        clarifying_options=[o.model_dump() for o in turn.clarifying_options],
    )
