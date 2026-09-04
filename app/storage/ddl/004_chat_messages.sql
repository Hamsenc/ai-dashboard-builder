-- Log transcript/audit lâu dài. KHÔNG phải nơi lưu session hot-path — state
-- hội thoại đang chạy giữ in-process trên instance Cloud Run trong phiên đó;
-- bảng này chỉ là bản ghi bền để audit/debug sau này.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.dashboard_builder_chat_messages` (
  message_id           STRING NOT NULL,
  session_id             STRING NOT NULL,
  dashboard_id              STRING,           -- NULL tới khi session này có blueprint
  turn_index                  INT64 NOT NULL,
  role                           STRING NOT NULL, -- 'user' | 'planner' | 'builder' | 'system'
  content                          STRING,
  structured_payload                 JSON,           -- đề xuất blueprint / lỗi validator / v.v.
  llm_model                             STRING,
  created_by                              STRING NOT NULL,
  created_at                                TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY session_id;
