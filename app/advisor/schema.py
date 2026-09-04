"""JSON schema cho output có cấu trúc của Advisor. Đây là NGUỒN THẬT truyền vào
`output_format` khi gọi Claude — Pydantic model bên dưới chỉ để type-hint/validate
lại phía Python, phải giữ khớp tay với dict JSON schema này (đúng convention của
planner/blueprint_schema.py — Advisor không sinh blueprint/SQL, chỉ tư vấn bảng).

Mỗi lượt Advisor trả về đúng 1 trong 3 hành động:
- "clarify": còn điểm chưa rõ để chọn đúng bảng, message_to_user là câu hỏi tiếp
  theo, recommendations/unsuitable rỗng.
- "recommend": đã đủ rõ, gợi ý 1+ bảng phù hợp kèm lý do; có thể kèm cả
  "unsuitable" để giải thích tại sao 1 bảng liên quan nhưng KHÔNG hợp (vd đúng
  domain nhưng sai grain).
- "not_available": không bảng nào trong danh sách đáp ứng được — PHẢI nói rõ
  thiếu chính xác cái gì trong missing_data, không được tự bịa hay gợi ý bừa
  (đúng luật cứng #1: chỉ dùng dữ liệu trong phạm vi đã cấp quyền)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CLARIFYING_OPTION_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "Câu hỏi ngắn, ngôn ngữ đời thường — KHÔNG dùng thuật ngữ/viết tắt kỹ thuật trừ khi user đã tự dùng từ đó trước",
        },
        "allow_multiple": {"type": "boolean", "description": "true nếu user có thể tick nhiều lựa chọn cùng lúc"},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Mỗi lựa chọn là 1 câu ngắn, dễ hiểu, KHÔNG dùng thuật ngữ kỹ thuật",
        },
    },
    "required": ["question", "allow_multiple", "options"],
    "additionalProperties": False,
}

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "table_id": {"type": "string", "description": "table_id đầy đủ dạng project.dataset.table, PHẢI nằm trong danh sách bảng được cung cấp"},
        "why": {"type": "string", "description": "Vì sao bảng này phù hợp với báo cáo user muốn làm — nói ngắn gọn, dễ hiểu"},
        "columns_to_use": {
            "type": "array", "items": {"type": "string"},
            "description": (
                "Tên cột SQL NGUYÊN VĂN (copy y hệt ký tự từ danh sách cột của bảng, "
                "vd 'doh_avail', 'sales_velocity_7d') — KHÔNG diễn giải, KHÔNG dịch sang "
                "tiếng Việt, KHÔNG thêm chú thích trong ngoặc. Đây là để user tự viết SQL, "
                "sai 1 ký tự là chạy lỗi. Rỗng nếu chưa đủ thông tin để gợi ý cột."
            ),
        },
        "caveats": {
            "type": "string",
            "description": "Lưu ý quan trọng khi dùng bảng này (vd chỉ có 1 thương hiệu, filter sẵn kênh nào đó, KPI liên quan còn Draft chưa xác nhận). Chuỗi rỗng nếu không có lưu ý gì.",
        },
    },
    "required": ["table_id", "why", "columns_to_use", "caveats"],
    "additionalProperties": False,
}

UNSUITABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_id": {"type": "string"},
        "why_not": {"type": "string", "description": "Vì sao bảng này liên quan nhưng KHÔNG phù hợp — giúp user hiểu tại sao bị loại thay vì thắc mắc"},
    },
    "required": ["table_id", "why_not"],
    "additionalProperties": False,
}

ADVISOR_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["clarify", "recommend", "not_available"]},
        "message_to_user": {
            "type": "string",
            "description": "Nội dung hiển thị cho user — câu hỏi làm rõ, lời giới thiệu ngắn cho các bảng gợi ý, hoặc lời báo thiếu dữ liệu kèm lý do cụ thể. Ngắn gọn 1-3 câu.",
        },
        "recommendations": {
            "type": "array", "items": RECOMMENDATION_SCHEMA,
            "description": "Chỉ có ý nghĩa khi action='recommend'. Mảng rỗng nếu action khác.",
        },
        "unsuitable": {
            "type": "array", "items": UNSUITABLE_SCHEMA,
            "description": "Bảng liên quan domain nhưng không phù hợp, kèm lý do — có thể có ở action='recommend' hoặc 'not_available'. Mảng rỗng nếu không có.",
        },
        "missing_data": {
            "type": "string",
            "description": "Chỉ có ý nghĩa khi action='not_available' — mô tả chính xác dữ liệu/chỉ số nào đang thiếu. Chuỗi rỗng nếu action khác.",
        },
        "clarifying_options": {
            "type": "array", "items": CLARIFYING_OPTION_GROUP_SCHEMA,
            "description": "Chỉ có ý nghĩa khi action='clarify'. Mảng rỗng nếu action khác, hoặc câu hỏi không tách thành lựa chọn rời rạc được.",
        },
    },
    "required": ["action", "message_to_user", "recommendations", "unsuitable", "missing_data", "clarifying_options"],
    "additionalProperties": False,
}
"""Lưu ý: mọi field nằm trong required dù chỉ có ý nghĩa với 1 action cụ thể — vì
SDK cần strict JSON schema (không hỗ trợ optional/nullable dễ dàng), giống hệt lý
do đã ghi trong planner/blueprint_schema.py. Advisor được yêu cầu (qua system
prompt) điền placeholder rỗng hợp lệ cho field không dùng tới; service.py lọc bỏ
field không khớp action trong from_raw(), không dựa vào giá trị placeholder."""


class ClarifyingOptionGroup(BaseModel):
    question: str
    allow_multiple: bool
    options: list[str]


class Recommendation(BaseModel):
    table_id: str
    why: str
    columns_to_use: list[str]
    caveats: str


class Unsuitable(BaseModel):
    table_id: str
    why_not: str


class AdvisorTurn(BaseModel):
    action: Literal["clarify", "recommend", "not_available"]
    message_to_user: str
    recommendations: list[Recommendation] = []
    unsuitable: list[Unsuitable] = []
    missing_data: str = ""
    clarifying_options: list[ClarifyingOptionGroup] = []

    @classmethod
    def from_raw(cls, raw: dict) -> "AdvisorTurn":
        recommendations = raw.get("recommendations") if raw.get("action") == "recommend" else []
        missing_data = raw.get("missing_data") if raw.get("action") == "not_available" else ""
        options = raw.get("clarifying_options") if raw.get("action") == "clarify" else []
        return cls(
            action=raw["action"],
            message_to_user=raw["message_to_user"],
            recommendations=[Recommendation.model_validate(r) for r in (recommendations or [])],
            unsuitable=[Unsuitable.model_validate(u) for u in (raw.get("unsuitable") or [])],
            missing_data=missing_data or "",
            clarifying_options=[ClarifyingOptionGroup.model_validate(o) for o in (options or [])],
        )
