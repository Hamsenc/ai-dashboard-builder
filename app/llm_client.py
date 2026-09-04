"""Wrapper LLM dùng chung cho Planner + Builder.

Dùng Claude Agent SDK (claude-agent-sdk), auth qua CLAUDE_CODE_OAUTH_TOKEN — KHÔNG
phải anthropic SDK + ANTHROPIC_API_KEY (2 cơ chế billing khác nhau: token này gắn
với subscription Claude Pro/Max/Team, sinh bằng `claude setup-token`).

Luôn tắt hết tool access (tools=[]) — đây là service chạy nền không người trực,
Planner/Builder chỉ được phép suy luận trên catalog + hội thoại rồi trả JSON/text,
không bao giờ được có quyền Bash/file/mạng như 1 phiên Claude Code bình thường.
"""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query


class LLMError(RuntimeError):
    pass


def _base_options(system_prompt: str, output_format: dict[str, Any] | None = None) -> ClaudeAgentOptions:
    cli_path = os.environ.get("CLAUDE_CLI_PATH") or None
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"),
        tools=[],  # không cấp bất kỳ tool nào — chặn hẳn từ SDK, không chỉ dựa vào prompt
        cli_path=cli_path,
        output_format=output_format,
        env={"CLAUDE_CODE_OAUTH_TOKEN": os.environ["CLAUDE_CODE_OAUTH_TOKEN"]},
    )


async def run_text(system_prompt: str, prompt: str) -> str:
    """Lượt hội thoại tự do (vd câu hỏi làm rõ của Planner) — trả về text thô,
    gộp từ các TextBlock trong AssistantMessage."""
    options = _base_options(system_prompt, output_format=None)
    chunks: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
    text = "".join(chunks)
    if not text:
        raise LLMError("Claude không trả về nội dung nào (rỗng) — kiểm tra CLAUDE_CODE_OAUTH_TOKEN/model.")
    return text


async def run_structured(system_prompt: str, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
    """Ép Claude trả JSON đúng schema (Blueprint, SQL+chart-config...) bằng
    output_format của Agent SDK. QUAN TRỌNG: kết quả structured KHÔNG nằm trong
    AssistantMessage/TextBlock như hội thoại thường — nó nằm ở
    ResultMessage.structured_output (đã parse sẵn thành dict, không phải string
    cần json.loads) — đã verify bằng call thật, không phải suy đoán từ tài liệu."""
    options = _base_options(system_prompt, output_format={"type": "json_schema", "schema": json_schema})

    result: ResultMessage | None = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result = message

    if result is None:
        raise LLMError("Không nhận được ResultMessage nào từ Claude.")
    if result.is_error:
        raise LLMError(f"Claude trả lỗi: subtype={result.subtype}, errors={result.errors}")
    if result.structured_output is None:
        raise LLMError(
            f"ResultMessage không có structured_output dù đã ép output_format. "
            f"stop_reason={result.stop_reason}, result_text={result.result!r}"
        )
    return result.structured_output
