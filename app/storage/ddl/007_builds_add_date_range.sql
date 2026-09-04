-- Thêm cột lưu khoảng ngày mặc định (đúng với blueprint.time_range lúc build) —
-- dùng làm giá trị @start_date/@end_date khi Refresh (không đổi phạm vi) hoặc lúc mở
-- lại dashboard lần đầu; bộ lọc ngày sống trên UI truyền giá trị khác để ghi đè tạm
-- thời, không ghi lại 2 cột này (chỉ đổi lúc build/rebuild thật).
ALTER TABLE `surya-495408.12_data_agent_log.raw_dashboard_builder_builds`
  ADD COLUMN IF NOT EXISTS default_start_date DATE,
  ADD COLUMN IF NOT EXISTS default_end_date DATE;
