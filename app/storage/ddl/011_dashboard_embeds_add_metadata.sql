-- Thêm cột ghi chú quản lý (tên người tạo, ghi chú prompt/schema) + cột lưu 1 file dữ
-- liệu (Excel/CSV) user tự tải lên làm nguồn "dữ liệu sống" thay thế cho BigQuery
-- (xem app/embeds/gcs_store.py, app/api/embed_view.py). event 'updated' mang lại
-- data_file_gcs_path cũ nếu không đổi file, đúng quy ước append-only hiện có.
ALTER TABLE `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
  ADD COLUMN IF NOT EXISTS owner_name STRING,
  ADD COLUMN IF NOT EXISTS prompt_note STRING,
  ADD COLUMN IF NOT EXISTS data_file_gcs_path STRING,
  ADD COLUMN IF NOT EXISTS data_file_name STRING;
