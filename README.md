# Data Explorer

Công cụ nội bộ giúp nhân viên hiểu dữ liệu công ty đang có để tự làm báo cáo:

1. Duyệt danh sách bảng ở các dataset tầng Serving đã cấp quyền (đọc live từ
   BigQuery `INFORMATION_SCHEMA`, làm giàu thêm mô tả nghiệp vụ từ Lark nếu có).
2. Xem trước vài chục dòng dữ liệu thật của 1 bảng để hình dung dữ liệu trông ra sao.
3. Chat với Advisor: mô tả báo cáo muốn làm → AI gợi ý bảng nào phù hợp, vì sao,
   cột nào nên dùng — hoặc nói rõ đang thiếu dữ liệu gì nếu không bảng nào đáp ứng.

App không sinh SQL, không tính KPI, không vẽ chart — sau khi tìm được đúng bảng,
user tự đi dựng báo cáo ở nơi khác (Looker Studio, BigQuery console...).

Bản trước (chat → blueprint → duyệt → build SQL → render dashboard) đã bị bỏ vì
chất lượng dashboard tự sinh không đạt yêu cầu — xem lịch sử git để tham khảo lại
nếu cần.

## Luật cứng

1. Chỉ dùng dữ liệu trong whitelist các dataset tầng Serving (`SERVING_DATASETS`)
   đã cấp quyền — không tự bịa, không tự mở rộng phạm vi. Advisor gợi ý ngoài phạm
   vi này phải trả `action="not_available"` và nói rõ thiếu gì (xem
   `app/advisor/prompts.py`). Mọi endpoint đọc bảng/preview phải qua
   `app/datasource/bq_meta.assert_in_scope()` trước khi chạm BigQuery.

## Hạ tầng đã có (project `surya-495408`, region `asia-southeast1`)

- Service account: `dashboard-builder@surya-495408.iam.gserviceaccount.com`
  (READER trên `00_serving_sales`/`00_serving_inventory`/`00_serving_operation`,
  WRITER trên `12_data_agent_log`, project-level `bigquery.jobUser`).
- GCS bucket catalog: `gs://surya-495408-dashboard-builder-catalog` (catalog Lark,
  dùng để làm giàu metadata bảng — không bắt buộc, app vẫn chạy nếu đọc lỗi).
- Bảng app (trong `12_data_agent_log`, tiền tố `raw_dashboard_builder_`):
  `chat_messages` (lịch sử hội thoại Advisor), `data_access_log` (audit ai xem/
  preview bảng nào). Còn `blueprints`/`builds`/`kpi_confirmations`/
  `v_current_blueprints` từ bản dashboard builder cũ — giữ lại để tra cứu lịch sử,
  không còn hàm ghi mới. DDL nguồn: `app/storage/ddl/*.sql`, áp dụng lại bằng
  `python scripts/apply_ddl.py`.

## Chạy cục bộ

```
cd app && ALLOW_DEV_USER_HEADER=true uvicorn main:app --reload --port 8000
```

Cần Application Default Credentials cho BigQuery
(`gcloud auth application-default login`, hoặc key của service account ở trên).
