-- 1 dòng mỗi lần chạy job catalog_sync. File JSON thật nằm trên GCS
-- (gs://surya-495408-dashboard-builder-catalog/catalog/<generated_at>.json);
-- bảng này là audit trail + nơi tra "bản catalog mới nhất là bản nào".
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.dashboard_builder_catalog_sync_runs` (
  sync_id           STRING NOT NULL,
  generated_at        TIMESTAMP NOT NULL,  -- cũng chính là định danh "version" của catalog
  gcs_uri                STRING NOT NULL,
  table_count               INT64,
  kpi_count                   INT64,
  status                         STRING NOT NULL, -- 'success' | 'partial' | 'failed'
  error_message                     STRING,
  triggered_by                        STRING NOT NULL -- 'cloud_scheduler' | email nếu chạy tay
)
PARTITION BY DATE(generated_at);
