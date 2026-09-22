-- View tiện dụng: sự kiện mới nhất theo (embed_id, shared_with) — giống pattern
-- 010_v_current_dashboard_embeds.sql. 1 share coi là còn hiệu lực khi sự kiện mới
-- nhất là 'shared' (chưa bị 'unshared' sau đó).
CREATE OR REPLACE VIEW `surya-495408.12_data_agent_log.raw_dashboard_builder_v_current_embed_shares` AS
SELECT *
FROM `surya-495408.12_data_agent_log.raw_dashboard_builder_embed_shares`
QUALIFY ROW_NUMBER() OVER (PARTITION BY embed_id, shared_with ORDER BY event_at DESC) = 1;
