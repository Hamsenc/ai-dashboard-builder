-- View tiện dụng: sự kiện mới nhất theo embed_id (giống pattern
-- 006_v_current_blueprints.sql) — 1 embed coi là còn hiệu lực khi event mới nhất
-- là 'created' (chưa bị 'revoked' sau đó).
CREATE OR REPLACE VIEW `surya-495408.12_data_agent_log.raw_dashboard_builder_v_current_embeds` AS
SELECT *
FROM `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds`
QUALIFY ROW_NUMBER() OVER (PARTITION BY embed_id ORDER BY event_at DESC) = 1;
