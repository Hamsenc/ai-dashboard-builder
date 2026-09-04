-- Blueprint đã duyệt -> artifact thực thi được, đã validate. Khác Blueprint
-- (spec nghiệp vụ, dễ đọc) ở chỗ Build là SQL+chart-config đã qua validator,
-- được app dùng để chạy thật và để Refresh.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_builds` (
  build_id                STRING NOT NULL,
  blueprint_id             STRING NOT NULL,  -- version blueprint cụ thể đã duyệt sinh ra build này
  dashboard_id               STRING NOT NULL,
  status                       STRING NOT NULL, -- 'active' | 'superseded' | 'failed'
  sql_per_kpi                    JSON NOT NULL, -- [{kpi_name, sql, chart_type, chart_config}]
  validator_status                 STRING NOT NULL, -- 'passed' | 'rejected'
  validator_report                   JSON,            -- bảng/cột đã đụng, các check đã chạy, số lần retry
  catalog_version_used                 STRING NOT NULL,
  created_by                             STRING NOT NULL,
  created_at                               TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY dashboard_id, status;
