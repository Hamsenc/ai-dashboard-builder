-- Data Explorer đọc/preview dữ liệu thật (kể cả cột PII, chỉ cảnh báo chứ không
-- che) cho mọi nhân viên đăng nhập được — cần vết audit ai đã xem bảng nào, khi
-- nào, bao nhiêu dòng, để truy vết được nếu cần sau này.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_data_access_log` (
  access_id     STRING NOT NULL,
  created_by    STRING NOT NULL,
  table_id      STRING NOT NULL,  -- project.dataset.table đầy đủ
  action        STRING NOT NULL,  -- 'preview' | 'view_detail' | 'list_tables'
  row_count     INT64,            -- số dòng thực trả về (preview); NULL cho các action khác
  created_at    TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY table_id, created_by;
