# LSR Data Explorer

Công cụ nội bộ 2 mảng: giúp nhân viên tự tìm đúng bảng dữ liệu, và giúp họ dựng/
chia sẻ dashboard vào Lark mà không cần biết code.

## 1. Data Explorer — duyệt bảng, xem trước, tư vấn chọn bảng

1. Duyệt danh sách bảng ở các dataset tầng Serving đã cấp quyền (đọc live từ
   BigQuery `INFORMATION_SCHEMA`, làm giàu thêm mô tả nghiệp vụ từ Lark nếu có).
2. Xem trước vài chục dòng dữ liệu thật của 1 bảng để hình dung dữ liệu trông ra sao.
3. Chat với Advisor: mô tả báo cáo muốn làm → AI gợi ý bảng nào phù hợp, vì sao,
   cột nào nên dùng — hoặc nói rõ đang thiếu dữ liệu gì nếu không bảng nào đáp ứng.

Advisor chỉ tư vấn chọn bảng — không tự sinh SQL, không tự tính KPI. Sau khi tìm
được đúng bảng, user tự đi dựng báo cáo ở nơi khác (Looker Studio, BigQuery
console...), hoặc chuyển sang mục 2 bên dưới nếu muốn 1 dashboard nhúng thẳng
vào Lark.

Bản trước (chat → blueprint → duyệt → build SQL → render dashboard tự động) đã
bị bỏ vì chất lượng dashboard tự sinh không đạt yêu cầu — xem lịch sử git để
tham khảo lại nếu cần.

## 2. Dashboard Embeds — dựng & chia sẻ dashboard vào Lark

Trang `/embeds.html`, có hướng dẫn chi tiết ở `/guide.html`. Không cần biết
code, có 3 cách tạo dashboard:

- **Upload file HTML tự viết** (tự code, hoặc nhờ AI/Claude Code viết hộ) — app
  chỉ host lại nguyên văn.
- **Dashboard mẫu dựng sẵn**: chọn 1 bảng BigQuery + vài widget (KPI/Bar/Line/
  Table), server tự lắp HTML (`app/embeds/template_gen.py`).
- Trong cả 2 cách, dashboard có thể gắn **nguồn dữ liệu sống**: 1-3 bảng
  BigQuery qua `data_query_spec` đã validate cứng phía server (không nhận SQL
  tự do, xem `app/embeds/query_spec.py`), hoặc 1 file Excel/CSV user tự tải lên
  (không cần nằm trong BigQuery) — dashboard tự đọc lại bằng SheetJS.

Mỗi dashboard có link riêng `/d/{embed_id}` — public, không cần đăng nhập để
xem, nhúng thẳng vào Lark (docs/base/wiki). Chủ sở hữu quản lý sửa/thu hồi/chia
sẻ (`view` hoặc `edit`) cho người khác hoặc cho toàn nội bộ (`*`) tại
`/embeds.html`.

## Đăng nhập & phân quyền

- Đăng nhập bằng Lark OAuth2 (`app/auth/lark_oauth.py`) — session cookie 12h,
  không lưu refresh token của Lark.
- 2 role: `embed` (được tạo/sửa dashboard) và `admin` (quản trị toàn hệ thống).
  `SUPER_ADMIN_EMAILS` (Config) luôn có cả 2 role, người khác được cấp qua
  `/admin.html` hoặc tự bấm "Yêu cầu cấp quyền" ở `/embeds.html` để admin duyệt.
- `/admin.html`: log đăng nhập, toàn bộ lịch sử tạo/sửa/thu hồi embed, top bảng/
  user dùng nhiều nhất, cấp/thu hồi role.

## Luật cứng

1. Chỉ dùng dữ liệu trong whitelist các dataset tầng Serving (`SERVING_DATASETS`)
   đã cấp quyền — không tự bịa, không tự mở rộng phạm vi. Advisor gợi ý ngoài phạm
   vi này phải trả `action="not_available"` và nói rõ thiếu gì (xem
   `app/advisor/prompts.py`). Mọi endpoint đọc bảng/preview/dựng query sống phải
   qua `app/datasource/bq_meta.assert_in_scope()` trước khi chạm BigQuery.
2. Endpoint xem dashboard (`/d/*`) là public, không đăng nhập — không bao giờ
   nhận SQL tự do từ client, chỉ nhận `data_query_spec` dạng JSON có cấu trúc,
   validate lại mọi tên bảng/cột với ground-truth thật trước khi ghép vào SQL
   (xem `app/embeds/query_spec.py`).

## Hạ tầng đã có (project `surya-495408`, region `asia-southeast1`)

- Service account: `dashboard-builder@surya-495408.iam.gserviceaccount.com`
  (READER trên `00_serving_sales`/`00_serving_inventory`/`00_serving_operation`,
  WRITER trên `12_data_agent_log`, project-level `bigquery.jobUser`).
- GCS bucket catalog: `gs://surya-495408-dashboard-builder-catalog` (catalog Lark,
  dùng để làm giàu metadata bảng — không bắt buộc, app vẫn chạy nếu đọc lỗi).
- GCS bucket embeds: `gs://surya-495408-dashboard-builder-embeds` (PRIVATE — host
  file HTML dashboard + file Excel/CSV dữ liệu sống, browser không bao giờ chạm
  trực tiếp, luôn qua app proxy).
- Bảng app (trong `12_data_agent_log`, tiền tố `raw_dashboard_builder_`):
  `chat_messages` (lịch sử hội thoại Advisor), `data_access_log` (audit ai xem/
  preview bảng nào), `dashboard_embeds` + `v_current_dashboard_embeds` (lịch sử
  + trạng thái hiện tại của từng embed), `dashboard_embed_shares` +
  `v_current_dashboard_embed_shares` (ai được chia sẻ embed nào), `login_log`
  (lịch sử đăng nhập Lark), `user_roles` + `v_current_user_roles` (phân quyền
  admin/embed). Tất cả append-only, "hiện tại" luôn là bản ghi mới nhất theo
  view `v_current_*`. DDL nguồn: `app/storage/ddl/*.sql`, áp dụng lại bằng
  `python scripts/apply_ddl.py`.

## Chạy cục bộ

```
cd app && ALLOW_DEV_USER_HEADER=true uvicorn main:app --reload --port 8000
```

Cần Application Default Credentials cho BigQuery
(`gcloud auth application-default login`, hoặc key của service account ở trên).
