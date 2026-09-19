-- View tiện dụng: sự kiện mới nhất theo (user_email, role) — giống pattern
-- 010_v_current_dashboard_embeds.sql. 1 role coi là đang hiệu lực khi sự kiện mới
-- nhất là 'granted'.
CREATE OR REPLACE VIEW `surya-495408.12_data_agent_log.raw_dashboard_builder_v_current_user_roles` AS
SELECT *
FROM `surya-495408.12_data_agent_log.raw_dashboard_builder_user_roles`
QUALIFY ROW_NUMBER() OVER (PARTITION BY user_email, role ORDER BY event_at DESC) = 1;
