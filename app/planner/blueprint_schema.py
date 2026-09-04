"""JSON schema cho output có cấu trúc của Planner. Đây là NGUỒN THẬT (source of
truth) truyền vào `output_format` khi gọi Claude — Pydantic model bên dưới chỉ để
type-hint/validate lại phía Python, phải giữ khớp tay với dict JSON schema này.

Mỗi lượt Planner trả về đúng 1 trong 3 hành động:
- "clarify": còn điểm chưa rõ, message_to_user là câu hỏi tiếp theo, KHÔNG có blueprint.
- "propose_blueprint": đã đủ rõ, có blueprint đầy đủ, message_to_user là lời giới thiệu ngắn.
- "refuse_out_of_scope": yêu cầu đụng tới dữ liệu/KPI ngoài whitelist Serving, message_to_user
  giải thích rõ phần nào ngoài phạm vi — ĐÚNG luật "cảnh báo ngay, không tự bịa".

Khi action="clarify", nên kèm `clarifying_options` — 1 hoặc vài câu hỏi ngắn dạng tick
chọn (KHÔNG bắt buộc user phải gõ), để user bấm thay vì gõ cả câu. Frontend hiển thị
mỗi group thành nút bấm được + luôn có 1 ô gõ tự do đi kèm cho trường hợp không khớp
lựa chọn nào. mảng rỗng nếu action != "clarify" hoặc câu hỏi không tách được thành lựa
chọn rời rạc (vd hỏi "khoảng thời gian nào" thì để trống, cho user gõ tự do).

Khi đang CHỈNH SỬA 1 dashboard đã tồn tại (current_blueprint được truyền vào prompt),
action="propose_blueprint" còn kèm:
- is_structural_change: false = chỉ đổi cosmetic (chart_type/sắp xếp...), KHÔNG đổi
  KPI/sources/dimensions/filters/time_range/granularity — API tầng trên sẽ tự áp dụng
  ngay, không bắt user bấm duyệt lại.
- is_structural_change: true = có đổi KPI/nguồn dữ liệu/phạm vi — API tầng trên BẮT
  BUỘC hiện diff cho user duyệt lại, không bao giờ tự áp dụng.
- change_summary: mô tả ngắn gọn cái gì đã đổi so với current_blueprint (rỗng nếu
  đây là dashboard hoàn toàn mới, không phải chỉnh sửa).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

KPI_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Tên KPI, ưu tiên khớp đúng tên trong kho KPI catalog nếu có"},
        "definition": {
            "type": "string",
            "description": "Định nghĩa/công thức — nếu KPI có trong catalog, PHẢI copy nguyên văn formula/business_definition, không tự diễn giải lại",
        },
        "status": {
            "type": "string",
            "enum": ["Active", "Draft", "custom"],
            "description": "Active/Draft nếu lấy từ kho KPI catalog; 'custom' nếu Planner tự tổng hợp từ cột thô (vd SUM 1 cột) và KPI này không có sẵn trong kho",
        },
        "chart_type": {"type": "string", "enum": ["line", "bar", "number", "table"]},
        "tile_agg": {
            "type": "string",
            "enum": ["sum", "last", "avg"],
            "description": (
                "Phép gộp để ra CON SỐ TỔNG QUAN của KPI này trên cả khoảng thời gian "
                "đang xem (hiển thị to ở thẻ đầu dashboard). Chọn SAI là ra con số headline "
                "sai, nên phải cân nhắc theo bản chất chỉ số:\n"
                "- 'sum': đại lượng CỘNG ĐƯỢC theo thời gian — doanh thu, giá vốn, lợi nhuận, "
                "số đơn, số lượng bán. Cộng 14 ngày lại ra tổng 14 ngày, có nghĩa.\n"
                "- 'last': đại lượng dạng TỒN/TRẠNG THÁI tại một thời điểm — số lượng tồn kho, "
                "số ngày tồn kho còn bán được, số dư. Cộng lại là vô nghĩa, chỉ lấy mốc mới nhất.\n"
                "- 'avg': tỷ lệ/đơn giá — tỷ lệ huỷ đơn, giá trị đơn trung bình. Cộng tỷ lệ của "
                "14 ngày lại là vô nghĩa.\n"
                "Không chắc thuộc loại nào thì PHẢI hỏi lại user ở bước clarify, không đoán."
            ),
        },
        "format": {
            "type": "string",
            "enum": ["number", "currency_vnd", "percent"],
            "description": (
                "Đơn vị để hiển thị: 'currency_vnd' cho số tiền VND (sẽ hiện kèm ₫), "
                "'percent' cho tỷ lệ phần trăm, 'number' cho số đếm/số lượng. Gắn sai đơn vị "
                "(vd gắn tiền tệ cho số đơn hàng) là nói sai với người đọc."
            ),
        },
        "top_n": {
            "type": "integer",
            "description": (
                "Số nhóm nhiều nhất được vẽ riêng khi KPI này có breakdown; phần còn lại tự "
                "gộp thành 'Khác'. Điền 0 để dùng mặc định (6) — chỉ điền số khác khi user yêu "
                "cầu rõ, vd 'chỉ xem 3 kênh lớn nhất'. Quá 8 là chart không đọc nổi."
            ),
        },
        "col_span": {
            "type": "integer",
            "enum": [0, 6, 12],
            "description": (
                "Bề rộng chart trên lưới 12 cột: 6 = nửa hàng, 12 = trọn hàng cho chỉ số quan "
                "trọng nhất hoặc chart có nhiều nhóm. Điền 0 để hệ thống tự xếp (mặc định nửa "
                "hàng, chart lẻ cuối cùng tự giãn ra trọn hàng)."
            ),
        },
    },
    "required": ["name", "definition", "status", "chart_type", "tile_agg", "format", "top_n", "col_span"],
    "additionalProperties": False,
}

CLARIFYING_OPTION_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "Câu hỏi ngắn, ngôn ngữ đời thường — KHÔNG dùng thuật ngữ/viết tắt kỹ thuật (vd DOH, COGS, GMV) trừ khi user đã tự dùng từ đó trước",
        },
        "allow_multiple": {"type": "boolean", "description": "true nếu user có thể tick nhiều lựa chọn cùng lúc"},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Mỗi lựa chọn là 1 câu ngắn, dễ hiểu, KHÔNG dùng thuật ngữ kỹ thuật — vd 'Tổng giá trị đơn hàng, chưa trừ giảm giá' thay vì 'GMV'",
        },
    },
    "required": ["question", "allow_multiple", "options"],
    "additionalProperties": False,
}

BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {"type": "string"},
            "description": "table_id đầy đủ dạng project.dataset.table, PHẢI nằm trong danh sách bảng của catalog",
        },
        "kpis": {"type": "array", "items": KPI_SCHEMA},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "array", "items": {"type": "string"}},
        "time_range": {"type": "string", "description": "vd '30 ngày gần nhất', 'tháng này', '2026-01-01 đến 2026-01-31'"},
        "granularity": {"type": "string", "enum": ["hour", "day", "week", "month"]},
        "refresh_policy": {"type": "string", "enum": ["manual"]},
    },
    "required": [
        "title", "description", "sources", "kpis", "dimensions",
        "filters", "time_range", "granularity", "refresh_policy",
    ],
    "additionalProperties": False,
}

PLANNER_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["clarify", "propose_blueprint", "refuse_out_of_scope"],
        },
        "message_to_user": {
            "type": "string",
            "description": "Nội dung hiển thị cho user — câu hỏi làm rõ, lời giới thiệu blueprint, hoặc lời từ chối kèm lý do cụ thể",
        },
        "blueprint": BLUEPRINT_SCHEMA,
        "clarifying_options": {
            "type": "array",
            "items": CLARIFYING_OPTION_GROUP_SCHEMA,
            "description": "Chỉ có ý nghĩa khi action='clarify'. Mảng rỗng nếu action khác, hoặc câu hỏi không tách thành lựa chọn rời rạc được.",
        },
        "is_structural_change": {
            "type": "boolean",
            "description": "Chỉ có ý nghĩa khi đang chỉnh sửa dashboard có sẵn (xem docstring module). Điền false nếu là dashboard mới/không áp dụng.",
        },
        "change_summary": {
            "type": "string",
            "description": "Mô tả đổi gì so với current_blueprint. Chuỗi rỗng nếu là dashboard mới/không áp dụng.",
        },
    },
    "required": ["action", "message_to_user", "blueprint", "clarifying_options", "is_structural_change", "change_summary"],
    "additionalProperties": False,
}
"""Lưu ý: `blueprint` nằm trong required dù action != propose_blueprint — vì SDK cần
strict JSON schema (mọi property phải required, không hỗ trợ optional/nullable dễ
dàng). Khi action="clarify"/"refuse_out_of_scope", Planner được yêu cầu (qua system
prompt) điền blueprint bằng placeholder rỗng hợp lệ — service.py bỏ qua field này
nếu action != propose_blueprint, không dựa vào nó. Tương tự is_structural_change/
change_summary chỉ có ý nghĩa thật khi đang sửa dashboard có sẵn."""


class KPISpec(BaseModel):
    name: str
    definition: str
    status: Literal["Active", "Draft", "custom"]
    chart_type: Literal["line", "bar", "number", "table"]
    # 4 field trình bày bên dưới thêm sau, nên PHẢI có default: blueprint đã lưu trong
    # BigQuery từ trước không có chúng, mà api/chat.py dựng lại Blueprint bằng Pydantic
    # rồi model_dump() — thiếu default là vỡ khi mở lại dashboard cũ. Giá trị default
    # đúng bằng hành vi renderer đang chạy trước khi có mấy field này.
    tile_agg: Literal["sum", "last", "avg"] = "sum"
    format: Literal["number", "currency_vnd", "percent"] = "number"
    top_n: int = 0
    col_span: Literal[0, 6, 12] = 0


class Blueprint(BaseModel):
    title: str
    description: str
    sources: list[str]
    kpis: list[KPISpec]
    dimensions: list[str]
    filters: list[str]
    time_range: str
    granularity: Literal["hour", "day", "week", "month"]
    refresh_policy: Literal["manual"]


class ClarifyingOptionGroup(BaseModel):
    question: str
    allow_multiple: bool
    options: list[str]


class PlannerTurn(BaseModel):
    action: Literal["clarify", "propose_blueprint", "refuse_out_of_scope"]
    message_to_user: str
    blueprint: Blueprint | None = None
    clarifying_options: list[ClarifyingOptionGroup] = []
    is_structural_change: bool = False
    change_summary: str = ""

    @classmethod
    def from_raw(cls, raw: dict) -> "PlannerTurn":
        blueprint = raw.get("blueprint") if raw.get("action") == "propose_blueprint" else None
        options = raw.get("clarifying_options") if raw.get("action") == "clarify" else []
        return cls(
            action=raw["action"],
            message_to_user=raw["message_to_user"],
            blueprint=Blueprint.model_validate(blueprint) if blueprint else None,
            clarifying_options=[ClarifyingOptionGroup.model_validate(o) for o in (options or [])],
            is_structural_change=raw.get("is_structural_change", False),
            change_summary=raw.get("change_summary", ""),
        )
