"""API tư vấn chọn bảng: 1 lượt = 1 request/response JSON (không streaming, cùng
quyết định MVP với chat.py cũ). Session hội thoại giữ in-process, mất khi restart
instance — chấp nhận được ở quy mô nội bộ công ty."""

from __future__ import annotations

import uuid
from typing import Any

from advisor.schema import AdvisorTurn
from advisor.service import ChatTurn, next_turn
from api.catalog import get_bq_client
from auth.deps import get_current_user
from datasource import bq_meta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
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


@router.post("/message", response_model=AdviseMessageResponse)
async def post_message(req: AdviseMessageRequest, user: str = Depends(get_current_user)):
    session_id = req.session_id or str(uuid.uuid4())
    session = _sessions.setdefault(session_id, {"history": []})

    # Lịch sử cho lượt LLM này giữ TẠM trong biến cục bộ, KHÔNG ghi vào
    # session["history"] cho tới khi next_turn() thành công — nếu ghi ngay rồi lỡ
    # next_turn() lỗi, phải rollback thủ công (dễ quên ở nhánh lỗi khác sau này).
    user_turn_index = len(session["history"])
    pending_history = session["history"] + [ChatTurn("user", req.message)]

    client = get_bq_client()
    # 3 lời gọi BigQuery đồng bộ trong 1 route async — bọc run_in_threadpool để
    # không đóng băng event loop trong lúc chờ (route bên api/catalog.py xử lý
    # việc này bằng cách khai báo hẳn `def` thường; ở đây không làm vậy được vì
    # hàm còn phải `await next_turn()` thật sự bất đồng bộ).
    await run_in_threadpool(
        bq_store.insert_chat_message,
        client, session_id=session_id, turn_index=user_turn_index,
        role="user", content=req.message, created_by=user,
    )
    tables = await run_in_threadpool(bq_meta.list_tables, client)

    try:
        turn: AdvisorTurn = await next_turn(tables, pending_history)
    except llm_client.LLMError as e:
        raise HTTPException(
            503, f"Trợ lý AI đang gặp sự cố, thử lại sau ít phút. Chi tiết: {e}"
        ) from e

    session["history"] = pending_history + [ChatTurn("advisor", turn.message_to_user)]

    await run_in_threadpool(
        bq_store.insert_chat_message,
        client, session_id=session_id, turn_index=user_turn_index + 1,
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
