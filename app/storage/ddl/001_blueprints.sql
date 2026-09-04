-- Một dòng = 1 phiên bản Blueprint. dashboard_id ổn định xuyên suốt vòng đời
-- dashboard; version tăng dần; "hiện hành" = version mới nhất theo dashboard_id.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.dashboard_builder_blueprints` (
  blueprint_id          STRING NOT NULL,   -- UUID, duy nhất theo từng version
  dashboard_id          STRING NOT NULL,   -- ổn định xuyên suốt các version của "cùng 1 dashboard"
  version                INT64 NOT NULL,   -- tăng dần trong phạm vi dashboard_id, bắt đầu từ 1
  parent_blueprint_id     STRING,          -- blueprint_id mà version này phái sinh từ (NULL cho v1)
  status                   STRING NOT NULL,  -- 'draft' | 'approved' | 'superseded' | 'archived'
  is_structural_change      BOOL,            -- NULL cho v1; true = đổi KPI/cấu trúc, false = chỉ cosmetic
  change_summary              STRING,          -- tóm tắt đổi gì, vì sao (người đọc được)
  spec                          JSON NOT NULL, -- Blueprint JSON đầy đủ: title, description, sources,
                                                -- kpis[], dimensions/filters, time_range, granularity,
                                                -- chart_type theo kpi, refresh_policy
  catalog_version_used           STRING NOT NULL, -- generated_at của catalog JSON dùng để tạo blueprint này
  created_by                       STRING NOT NULL, -- Lark user id/email
  created_at                         TIMESTAMP NOT NULL,
  approved_by                          STRING,          -- NULL tới khi được duyệt
  approved_at                            TIMESTAMP
)
PARTITION BY DATE(created_at)
CLUSTER BY dashboard_id, status;
