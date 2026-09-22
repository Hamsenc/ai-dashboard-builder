-- Lưu danh sách tên cột (header) đọc được từ lần upload file Excel/CSV gần nhất của
-- 1 embed, dùng để cảnh báo chủ sở hữu nếu lần re-upload sau có cột khác (thêm/bớt)
-- so với lần trước — xem app/api/embeds.py::_extract_file_columns(). NULL nếu
-- dashboard không dùng nguồn file, hoặc file không parse được cột (vd .xls cũ).
ALTER TABLE `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
  ADD COLUMN IF NOT EXISTS data_file_columns JSON;
