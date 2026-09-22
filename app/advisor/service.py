"""Vòng lặp hội thoại của Advisor: nhận toàn bộ lịch sử chat + danh sách bảng, trả
về đúng 1 AdvisorTurn (clarify / recommend / not_available). Cùng cấu trúc với
planner/service.py — mỗi lượt gọi lại `run_structured` với TOÀN BỘ lịch sử hội
thoại nhét vào prompt, không dùng session/resume của Agent SDK (đơn giản, dễ
audit, đủ dùng cho quy mô nội bộ công ty)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from advisor.prompts import build_system_prompt
from advisor.schema import ADVISOR_TURN_SCHEMA, AdvisorTurn

import llm_client


@dataclass
class ChatTurn:
    role: Literal["user", "advisor"]
    content: str


def _render_transcript(history: list[ChatTurn]) -> str:
    lines = []
    for turn in history:
        speaker = "User" if turn.role == "user" else "Advisor (bạn, lượt trước)"
        lines.append(f"{speaker}: {turn.content}")
    return "\n\n".join(lines)


def sanitize_turn(turn: AdvisorTurn, tables: list[dict[str, Any]]) -> AdvisorTurn:
    """Chặn hallucination còn sót lại sau prompt: dù đã đưa cột thật vào system
    prompt, LLM vẫn có thể bịa table_id/tên cột không tồn tại — đúng lỗi bắt được
    lúc test thủ công ("stock_composition" không phải cột thật). Đối chiếu lại với
    ground-truth `tables` (từ bq_meta, không phải từ output LLM) trước khi trả về
    cho user, cùng triết lý với builder/validator.py: không tin tuyệt đối output
    LLM khi nó ảnh hưởng tới việc user viết SQL sai."""
    columns_by_table = {t["table_id"]: {c["name"] for c in t.get("columns", [])} for t in tables}

    clean_recs = []
    for r in turn.recommendations:
        valid_cols = columns_by_table.get(r.table_id)
        if valid_cols is None:
            continue  # table_id bịa ra, không có thật trong danh sách — bỏ hẳn gợi ý này
        r.columns_to_use = [c for c in r.columns_to_use if c in valid_cols]
        clean_recs.append(r)
    turn.recommendations = clean_recs
    turn.unsuitable = [u for u in turn.unsuitable if u.table_id in columns_by_table]
    return turn


async def next_turn(tables: list[dict[str, Any]], history: list[ChatTurn]) -> AdvisorTurn:
    if not history or history[-1].role != "user":
        raise ValueError("history phải kết thúc bằng 1 lượt user")

    system_prompt = build_system_prompt(tables)
    transcript = _render_transcript(history)
    prompt = (
        f"{transcript}\n\n"
        "---\n"
        "Dựa trên toàn bộ hội thoại trên, sinh ra lượt phản hồi tiếp theo của Advisor "
        "đúng theo schema đã cung cấp."
    )

    raw = await llm_client.run_structured(system_prompt, prompt, ADVISOR_TURN_SCHEMA)
    turn = AdvisorTurn.from_raw(raw)
    return sanitize_turn(turn, tables)
