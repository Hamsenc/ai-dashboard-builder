-- Append-only log cấp/thu hồi quyền cho user, thay whitelist tĩnh
-- (Config.UPLOAD_WHITELIST_EMAILS) bằng thứ admin bật/tắt được qua UI (/admin.html)
-- không cần sửa code/deploy lại. 2 role: 'admin' (xem log, phân quyền — chỉ
-- SUPER_ADMIN_EMAILS mới cấp được) và 'embed' (tạo/sửa/xoá dashboard embed).
-- Trạng thái hiện tại suy ra từ bản ghi mới nhất theo (user_email, role), xem
-- 014_v_current_user_roles.sql — cùng quy ước với raw_dashboard_builder_embeds.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_user_roles` (
  role_event_id STRING NOT NULL,
  user_email    STRING NOT NULL,
  role          STRING NOT NULL,   -- 'admin' | 'embed'
  event         STRING NOT NULL,   -- 'granted' | 'revoked'
  granted_by    STRING NOT NULL,
  event_at      TIMESTAMP NOT NULL
)
PARTITION BY DATE(event_at)
CLUSTER BY user_email;
