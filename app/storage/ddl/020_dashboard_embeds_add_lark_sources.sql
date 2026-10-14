-- Nguồn "dữ liệu sống" từ Lark Base: {tên: link Base}, xem app/embeds/lark_source.py.
-- NULL nếu dashboard không dùng nguồn Lark.
ALTER TABLE `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
  ADD COLUMN IF NOT EXISTS data_lark_sources JSON;

-- Tạo lại view (y hệt 018) để schema view có cột mới.
CREATE OR REPLACE VIEW `surya-495408.12_data_agent_log.raw_dashboard_builder_v_current_embeds` AS
SELECT
  *,
  FIRST_VALUE(created_by) OVER (PARTITION BY embed_id ORDER BY event_at ASC) AS owner_email
FROM `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
QUALIFY ROW_NUMBER() OVER (PARTITION BY embed_id ORDER BY event_at DESC) = 1;
