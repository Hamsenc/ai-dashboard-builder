"""Vòng lặp hội thoại của Planner: nhận toàn bộ lịch sử chat + catalog, trả về
đúng 1 PlannerTurn (clarify / propose_blueprint / refuse_out_of_scope).

MVP: mỗi lượt gọi lại `run_structured` với TOÀN BỘ lịch sử hội thoại nhét vào prompt
(không dùng session/resume của Agent SDK) — đơn giản, dễ audit (mỗi lượt độc lập,
không phụ thuộc state ẩn phía CLI), đủ dùng cho quy mô nội bộ công ty. Có thể đổi
sang continue_conversation/resume của SDK sau nếu cần giảm token lặp lại."""

from __future__ import annotations

from typing import Any, Literal

from planner.blueprint_schema import PLANNER_TURN_SCHEMA, PlannerTurn
from planner.prompts import build_system_prompt

import llm_client


class ChatTurn:
    def __init__(self, role: Literal["user", "planner"], content: str):
        self.role = role
        self.content = content


def _render_transcript(history: list[ChatTurn]) -> str:
    lines = []
    for turn in history:
        speaker = "User" if turn.role == "user" else "Planner (bạn, lượt trước)"
        lines.append(f"{speaker}: {turn.content}")
    return "\n\n".join(lines)


async def next_turn(
    catalog: dict[str, Any],
    history: list[ChatTurn],
    current_blueprint: dict[str, Any] | None = None,
) -> PlannerTurn:
    if not history or history[-1].role != "user":
        raise ValueError("history phải kết thúc bằng 1 lượt user")

    system_prompt = build_system_prompt(catalog, current_blueprint=current_blueprint)
    transcript = _render_transcript(history)
    prompt = (
        f"{transcript}\n\n"
        "---\n"
        "Dựa trên toàn bộ hội thoại trên, sinh ra lượt phản hồi tiếp theo của Planner "
        "đúng theo schema đã cung cấp."
    )

    raw = await llm_client.run_structured(system_prompt, prompt, PLANNER_TURN_SCHEMA)
    return PlannerTurn.from_raw(raw)
