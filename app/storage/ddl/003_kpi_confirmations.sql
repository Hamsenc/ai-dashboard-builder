-- Audit append-only: mỗi lần 1 KPI Status=Draft được dùng/xác nhận lại.
-- Đây là bằng chứng cụ thể cho luật "không bao giờ âm thầm đổi KPI".
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_kpi_confirmations` (
  confirmation_id            STRING NOT NULL,
  blueprint_id                 STRING NOT NULL,
  dashboard_id                    STRING NOT NULL,
  kpi_name                          STRING NOT NULL,
  kpi_table_id                        STRING,          -- Table_ID từ kho KPI (Lark "04. Business Logic - KPI")
  kpi_status_at_confirmation             STRING NOT NULL, -- 'Draft' | 'Active', snapshot tại thời điểm xác nhận
  kpi_formula_text                         STRING NOT NULL, -- công thức đã hiển thị & được xác nhận (snapshot)
  kpi_caveat_text                            STRING,          -- nguyên văn cảnh báo đã hiển thị (snapshot)
  catalog_version_used                         STRING NOT NULL,
  action                                          STRING NOT NULL, -- 'initial_confirm' | 're_confirm_after_drift'
  confirmed_by                                      STRING NOT NULL,
  confirmed_at                                        TIMESTAMP NOT NULL
)
PARTITION BY DATE(confirmed_at)
CLUSTER BY dashboard_id, kpi_name;
