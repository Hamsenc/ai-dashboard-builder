# Preview harness cho renderer dashboard

Xem trước thay đổi của `app/web/renderer.js` trên **dữ liệu thật**, so sánh cạnh bản
đang chạy production — không cần đăng nhập Lark, không cần chạy FastAPI, không tốn
query BigQuery mỗi lần vẽ lại.

## Chạy

```bash
python3 -m http.server 8765        # từ thư mục gốc repo
open http://localhost:8765/preview/
```

Sửa `app/web/renderer.js` → F5 → thấy ngay khác biệt ở cột "SAU".

Chốt sẵn trạng thái qua URL để chụp ảnh hoặc gửi link:
`?mode=after|before|both`, `?theme=light|dark`, `?fx=<tên fixture>`.

## Fixture đang có

| Tên | Ca kiểm thử |
|---|---|
| `doanh_thu` | 3 KPI, 16 kênh × 14 ngày — ca gốc gây ra bản dashboard xấu |
| `kinh_doanh_4kpi` | 4 KPI có 1 KPI dạng số; nhiều dòng trên cùng 1 mốc thời gian |
| `gmv_don_gian` | 1 số + 1 đường, không tách nhóm; 2 KPI TRÙNG TÊN |
| `phase2_demo` | Các field trình bày Phase 2: `tile_agg` (sum/last), `format` (currency_vnd/percent/number), `top_n`, `col_span`. Số liệu vẫn là số thật của `doanh_thu`, chỉ ghép lại và khai thêm field — sinh bằng scratchpad script, không phải từ BigQuery |

Chưa có fixture nào phủ `chart_type = "table"` — hiện không dashboard nào có build
active dùng dạng bảng.

## Vì sao nằm ngoài `app/`

`app/web/` được `StaticFiles` mount ở `/` **không qua xác thực**, và Dockerfile
`COPY app/ ./app/`. Fixture chứa số GMV/lợi nhuận thật — để trong `app/web/` là công
khai ra internet. Thư mục `preview/` không bao giờ được copy vào image production.

## Sinh lại fixture

```bash
python3 preview/gen_fixture.py <dashboard_id> <start> <end> preview/fixtures/<tên>.json
# vd: python3 preview/gen_fixture.py doanh_thu 2026-08-22 2026-09-04 preview/fixtures/doanh_thu.json
```

Script chạy lại **đúng** `sql_per_kpi` của build đang active trên BigQuery (qua `bq`
CLI, cần `gcloud auth application-default login`) rồi ghép thành y hệt response của
`GET /api/dashboard/{id}` — nên fixture luôn khớp shape mà renderer nhận trong app thật.
Thêm fixture mới thì thêm 1 `<option>` vào `#fixture` trong `preview/index.html`.

## `renderer-baseline.js`

Bản đóng băng của renderer **trước Phase 0**, chỉ để làm cột "TRƯỚC". Không sửa, không
bao giờ load trong app thật.
