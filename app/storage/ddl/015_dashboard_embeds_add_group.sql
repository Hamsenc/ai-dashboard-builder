-- Thêm cột phân nhóm (folder) cho Dashboard Embeds — mỗi dashboard thuộc 1 nhóm duy
-- nhất do chủ sở hữu tự đặt tên tự do, dùng để gọn danh sách dài ở embeds.html.
-- NULL/rỗng = chưa phân nhóm. event 'updated' mang lại giá trị cũ nếu không đổi,
-- đúng quy ước append-only hiện có (xem 011_dashboard_embeds_add_metadata.sql).
ALTER TABLE `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
  ADD COLUMN IF NOT EXISTS group_name STRING;
