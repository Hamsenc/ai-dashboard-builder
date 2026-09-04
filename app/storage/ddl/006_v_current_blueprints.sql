-- View tiện dụng: phiên bản mới nhất theo dashboard_id, cho màn "dashboard của tôi".
CREATE OR REPLACE VIEW `surya-495408.12_data_agent_log.raw_dashboard_builder_v_current_blueprints` AS
SELECT *
FROM `surya-495408.12_data_agent_log.raw_dashboard_builder_blueprints`
QUALIFY ROW_NUMBER() OVER (PARTITION BY dashboard_id ORDER BY version DESC) = 1;
