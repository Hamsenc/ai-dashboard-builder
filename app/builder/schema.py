"""JSON schema cho output có cấu trúc của Builder: Blueprint đã duyệt -> 1 SQL SELECT
cho mỗi KPI + field để vẽ chart. Nguồn thật cho `output_format`, giữ khớp tay với
QuerySpec/BuilderOutput bên dưới."""

from __future__ import annotations

import datetime

from pydantic import BaseModel

BUILDER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "default_start_date": {
            "type": "string",
            "description": (
                "Ngày bắt đầu (YYYY-MM-DD) tương ứng với blueprint.time_range, tính theo "
                "ngày hiện tại lúc build. Dùng làm giá trị mặc định cho @start_date khi "
                "user chưa đổi bộ lọc ngày."
            ),
        },
        "default_end_date": {
            "type": "string",
            "description": "Ngày kết thúc (YYYY-MM-DD) tương ứng với blueprint.time_range.",
        },
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kpi_name": {"type": "string"},
                    "sql": {
                        "type": "string",
                        "description": (
                            "Đúng 1 câu SELECT (được phép UNION/CTE), mọi table reference "
                            "PHẢI ở dạng đầy đủ `project.dataset.table` lấy nguyên văn từ "
                            "catalog['tables'][*]['table_id'], chỉ dùng cột có thật trong "
                            "catalog['tables'][*]['columns']. Áp dụng đúng dimensions/filters/"
                            "granularity của blueprint. Điều kiện lọc theo NGÀY chính PHẢI dùng "
                            "BigQuery named parameter `@start_date`/`@end_date` (kiểu DATE, vd "
                            "`WHERE date BETWEEN @start_date AND @end_date`) — KHÔNG hardcode "
                            "DATE_SUB(CURRENT_DATE(), ...) hay ngày cụ thể, để sau này đổi bộ "
                            "lọc ngày chỉ cần chạy lại đúng SQL với tham số khác, không cần sinh "
                            "SQL mới."
                        ),
                    },
                    "x_field": {"type": "string", "description": "Tên cột dùng làm trục X (thường là thời gian hoặc dimension chính)"},
                    "y_field": {"type": "string", "description": "Tên cột/alias dùng làm giá trị KPI (trục Y)"},
                    "series_field": {
                        "type": "string",
                        "description": (
                            "Tên cột dùng để TÁCH thành nhiều đường/cột riêng (vd 'brand_name' khi "
                            "blueprint.dimensions có yêu cầu so sánh theo thương hiệu). Chuỗi rỗng "
                            "nếu KPI này không có breakdown (chỉ 1 đường/cột duy nhất) — TUYỆT ĐỐI "
                            "không điền field vào đây nếu field đó không có trong blueprint.dimensions, "
                            "vì SQL sẽ GROUP BY theo nó và làm số liệu bị tách vụn ngoài ý muốn.\n"
                            "Case đặc biệt — so sánh THỰC TẾ vs CHỈ TIÊU (target): viết SQL dạng "
                            "`SELECT date, 'Thực tế' AS series, actual_value AS value FROM ... "
                            "UNION ALL SELECT date, 'Chỉ tiêu' AS series, target_value AS value "
                            "FROM ...` (cả 2 vế cùng lọc theo @start_date/@end_date, cùng alias "
                            "cột value/date), rồi đặt series_field='series' — không cần chart_type "
                            "riêng, render như multi-series line bình thường."
                        ),
                    },
                },
                "required": ["kpi_name", "sql", "x_field", "y_field", "series_field"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["default_start_date", "default_end_date", "queries"],
    "additionalProperties": False,
}


class QuerySpec(BaseModel):
    kpi_name: str
    sql: str
    x_field: str
    y_field: str
    series_field: str = ""


class BuilderOutput(BaseModel):
    default_start_date: datetime.date
    default_end_date: datetime.date
    queries: list[QuerySpec]
