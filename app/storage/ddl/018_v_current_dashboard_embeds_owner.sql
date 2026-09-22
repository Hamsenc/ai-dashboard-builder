-- Sửa lại v_current_dashboard_embeds: thêm cột owner_email = created_by của event
-- 'created' gốc (cố định vĩnh viễn theo embed_id, không đổi dù ai sửa sau này).
-- Trước đây "chủ sở hữu" bị suy từ created_by của bản ghi MỚI NHẤT — nghĩa là ai
-- sửa cuối cùng thì tự nghiễm nhiên thành chủ sở hữu, phá vỡ model chia sẻ (share
-- quyền 'edit' không được đoạt quyền sở hữu, xem 016_dashboard_embed_shares.sql).
-- created_by vẫn giữ nguyên ý nghĩa cũ: email người thao tác ĐÚNG sự kiện đó (dùng
-- cho audit log ở /admin.html) — owner_email mới là cột dùng để xác định "dashboard
-- của ai" (app/storage/embeds_store.py, app/api/embeds.py).
CREATE OR REPLACE VIEW `surya-495408.12_data_agent_log.raw_dashboard_builder_v_current_embeds` AS
SELECT
  *,
  FIRST_VALUE(created_by) OVER (PARTITION BY embed_id ORDER BY event_at ASC) AS owner_email
FROM `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
QUALIFY ROW_NUMBER() OVER (PARTITION BY embed_id ORDER BY event_at DESC) = 1;
