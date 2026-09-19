-- Log mỗi lần đăng nhập thành công qua Lark OAuth (app/auth/lark_oauth.py callback)
-- — cần cho trang /admin.html theo dõi ai đã đăng nhập, khi nào. Append-only,
-- không có "trạng thái hiện tại" nào cần suy ra nên không cần view riêng.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_login_log` (
  login_id      STRING NOT NULL,
  email         STRING NOT NULL,
  name          STRING,
  lark_user_id  STRING,
  created_at    TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY email;
