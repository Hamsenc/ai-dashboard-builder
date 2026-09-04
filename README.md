# AI Dashboard Builder

1 trang chat: user mô tả dashboard muốn có → AI hỏi làm rõ → đề xuất Blueprint (dễ đọc,
không phải SQL) → user duyệt → AI sinh SQL đã validate + render dashboard live trên
BigQuery → chat tiếp để chỉnh sửa / nút Refresh để lấy data mới.

Chi tiết kiến trúc, quyết định, và thứ tự build: xem plan tại
`~/.claude/plans/file-json-n-y-shiny-papert.md`.

## Luật cứng

1. Chỉ dùng dữ liệu trong whitelist Layer=Serving đã cấp quyền — không tự bịa, không tự
   mở rộng phạm vi. Yêu cầu ngoài phạm vi phải được cảnh báo ngay ở bước Clarify.
2. Không bao giờ âm thầm đổi định nghĩa KPI. KPI `Status=Draft` trong kho KPI (Lark "04.
   Business Logic - KPI") phải hiển thị nguyên văn cảnh báo và được xác nhận tường minh
   trước khi dùng — ghi vào `raw_dashboard_builder_kpi_confirmations`.

## Hạ tầng đã có (project `surya-495408`, region `asia-southeast1`)

- Service account: `dashboard-builder@surya-495408.iam.gserviceaccount.com`
  (READER trên `00_serving_sales`/`00_serving_inventory`/`00_serving_operation`,
  WRITER trên `12_data_agent_log`, project-level `bigquery.jobUser`).
- GCS bucket catalog: `gs://surya-495408-dashboard-builder-catalog`.
- Bảng app (trong `12_data_agent_log`, tiền tố `raw_dashboard_builder_`): `blueprints`,
  `builds`, `kpi_confirmations`, `chat_messages`, `catalog_sync_runs`, view
  `v_current_blueprints`. DDL nguồn: `app/storage/ddl/*.sql`, áp dụng lại bằng
  `python scripts/apply_ddl.py`.

## Trạng thái

Mới có hạ tầng GCP + scaffold thư mục + DDL. Chưa có code logic (catalog_sync, Planner,
Builder, validator, FastAPI app, Lark OAuth) — xem "Thứ tự build theo giai đoạn" trong
plan để biết thứ tự làm tiếp, bắt đầu từ catalog_sync (Phase 2).
