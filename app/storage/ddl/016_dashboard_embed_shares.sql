-- Append-only log chia sẻ Dashboard Embeds cho user khác thấy trong DANH SÁCH quản lý
-- ở embeds.html — KHÔNG ảnh hưởng link công khai /d/{id} (link đó vẫn public-by-link
-- như cũ, xem app/api/embed_view.py). shared_with là email cụ thể, hoặc '*' nghĩa là
-- chia sẻ cho TẤT CẢ user nội bộ (bất kỳ ai đăng nhập Lark). permission: 'view' (chỉ
-- xem trong danh sách) hoặc 'edit' (được sửa tên/ghi chú/dữ liệu sống, KHÔNG được thu
-- hồi link — chỉ chủ sở hữu (created_by) hoặc admin thu hồi được, xem
-- api/embeds.py._assert_can_revoke). Trạng thái hiện tại suy ra từ bản ghi mới nhất
-- theo (embed_id, shared_with), xem 017_v_current_dashboard_embed_shares.sql.
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_embed_shares` (
  share_id    STRING NOT NULL,
  embed_id    STRING NOT NULL,
  shared_with STRING NOT NULL,  -- email (thường hoá lowercase), hoặc '*' = tất cả user nội bộ
  permission  STRING NOT NULL,  -- 'view' | 'edit'
  event       STRING NOT NULL,  -- 'shared' | 'unshared'
  shared_by   STRING NOT NULL,
  event_at    TIMESTAMP NOT NULL
)
PARTITION BY DATE(event_at)
CLUSTER BY embed_id;
