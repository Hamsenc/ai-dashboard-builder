-- Append-only log các sự kiện embed dashboard (tạo mới / thu hồi). Không UPDATE,
-- đúng quy ước insert-only của app/storage/bq_store.py — trạng thái hiện tại suy
-- ra từ bản ghi mới nhất theo embed_id, xem raw_dashboard_builder_v_current_embeds
-- (010_v_current_dashboard_embeds.sql).
CREATE TABLE IF NOT EXISTS `surya-495408.12_data_agent_log.raw_dashboard_builder_embeds` (
  embed_id        STRING NOT NULL,   -- id ngẫu nhiên dùng trong URL /d/{embed_id}
  event           STRING NOT NULL,   -- 'created' | 'revoked'
  title           STRING,            -- NULL khi event='revoked'
  created_by      STRING NOT NULL,   -- email người thao tác (upload hoặc revoke)
  gcs_path        STRING,            -- blob path HTML trong EMBEDS_GCS_BUCKET, NULL khi event='revoked'
  data_table_id   STRING,            -- project.dataset.table nguồn cho query sống, NULL nếu dashboard tĩnh
  data_query_spec JSON,              -- spec truy vấn đã validate (xem app/embeds/query_spec.py), NULL nếu tĩnh
  event_at        TIMESTAMP NOT NULL
)
PARTITION BY DATE(event_at)
CLUSTER BY embed_id;
