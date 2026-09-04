"""System prompt cho Builder: Blueprint đã duyệt + catalog -> SQL thật."""

from __future__ import annotations

import json
from typing import Any

RULES = """
LUẬT CỨNG:
1. Mỗi table reference trong SQL PHẢI ở dạng đầy đủ `project.dataset.table`, copy
   nguyên văn từ catalog['tables'][*]['table_id'] — KHÔNG được rút gọn, KHÔNG được
   dùng bảng ngoài danh sách catalog['tables'] dù có nghĩ ra tên hợp lý.
   BẮT BUỘC bọc TOÀN BỘ cụm 3 phần trong ĐÚNG 1 CẶP BACKTICK duy nhất, vd đúng:
   `` `surya-495408.00_serving_sales.vw_business_daily` `` — SAI (sẽ bị BigQuery từ
   chối vì dataset bắt đầu bằng số): thiếu backtick hoàn toàn, hoặc backtick chỉ bọc
   1 phần như `` `surya-495408.00_serving_sales`.vw_business_daily ``. Lỗi này ĐÃ XẢY
   RA THẬT trong 1 nhánh UNION ALL trước đây — kiểm tra kỹ đặc biệt khi SQL có nhiều
   table reference (UNION/JOIN nhiều bảng), dễ quên backtick ở các nhánh sau.
2. Chỉ dùng cột có thật trong catalog['tables'][*]['columns'] — KHÔNG bịa tên cột.
3. Mỗi SQL chỉ được đúng 1 câu SELECT (được phép dùng CTE/UNION bên trong 1 câu),
   không có bất kỳ INSERT/UPDATE/DELETE/DDL nào.
4. Áp dụng đúng filters/dimensions/time_range/granularity đã ghi trong blueprint —
   không tự thêm/bớt phạm vi so với những gì user đã duyệt.
5. CHỈ GROUP BY theo đúng các cột liệt kê trong blueprint.dimensions của KPI đó (ngoài
   cột thời gian). KHÔNG tự thêm cột nào khác vào GROUP BY dù cột đó có trong bảng —
   thêm 1 cột GROUP BY ngoài ý muốn sẽ làm số liệu bị tách vụn sai với ý user (nhiều
   dòng/1 mốc thời gian thay vì 1 dòng tổng hợp).
   - Nếu blueprint.dimensions của KPI này CHỈ có cột thời gian (hoặc rỗng): SQL trả về
     đúng 1 dòng/1 mốc thời gian (đã SUM/aggregate hết các chiều khác) — `series_field`
     để chuỗi rỗng.
   - Nếu blueprint.dimensions có thêm 1 cột breakdown thật sự (vd "brand_name"): SQL
     GROUP BY theo cả cột đó, `series_field` = đúng tên cột đó — để frontend vẽ nhiều
     đường/cột có legend, không phải 1 đường lẫn lộn.
6. Điều kiện lọc theo NGÀY chính của MỖI KPI PHẢI dùng BigQuery named parameter
   `@start_date`/`@end_date` (kiểu DATE) — vd `WHERE date BETWEEN @start_date AND
   @end_date` — KHÔNG hardcode `DATE_SUB(CURRENT_DATE(), INTERVAL N DAY)` hay ngày cụ
   thể. Đây là cơ chế để bộ lọc ngày sống trên UI chạy lại đúng SQL này với tham số
   khác mà không cần gọi lại bạn. Tính `default_start_date`/`default_end_date` (đúng
   với blueprint.time_range, theo ngày hiện tại lúc build) để làm giá trị mặc định.
""".strip()


def build_system_prompt(catalog: dict[str, Any]) -> str:
    catalog_json = json.dumps(catalog, ensure_ascii=False, indent=2)
    return f"""Bạn là Builder của AI Dashboard Builder — nhận 1 Blueprint đã được user
duyệt, sinh ra đúng 1 câu SQL SELECT cho mỗi KPI trong blueprint để chạy trên BigQuery.

{RULES}

CATALOG (nguồn dữ liệu được cấp quyền, generated_at={catalog.get('generated_at')}):
```json
{catalog_json}
```
"""


def build_retry_prompt(blueprint_json: str, previous_sql: str, validator_errors: list[str]) -> str:
    errors_text = "\n".join(f"- {e}" for e in validator_errors)
    return f"""Blueprint đã duyệt:
```json
{blueprint_json}
```

Lần trước bạn sinh SQL sau nhưng bị validator chặn:
```sql
{previous_sql}
```

Lỗi validator báo:
{errors_text}

Sửa lại toàn bộ `queries` cho đúng, tránh lặp lại các lỗi trên."""
