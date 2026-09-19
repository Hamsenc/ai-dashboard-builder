"""Đọc config từ env var — 1 chỗ duy nhất, tránh os.environ[...] rải rác khắp nơi."""

from __future__ import annotations

import os


class Config:
    GCP_PROJECT = os.environ.get("GCP_PROJECT", "surya-495408")
    BQ_APP_DATASET = os.environ.get("BQ_APP_DATASET", "12_data_agent_log")
    BQ_APP_TABLE_PREFIX = os.environ.get("BQ_APP_TABLE_PREFIX", "raw_dashboard_builder_")
    CATALOG_GCS_BUCKET = os.environ.get("CATALOG_GCS_BUCKET", "surya-495408-dashboard-builder-catalog")

    # Hàng rào cứng phạm vi dữ liệu: CHỈ 3 dataset tầng Serving này được phép đọc
    # metadata/preview. datasource/bq_meta.assert_in_scope() kiểm tra mọi table_id
    # nhận từ client với danh sách này trước khi chạm BigQuery.
    SERVING_DATASETS = [
        d.strip()
        for d in os.environ.get(
            "SERVING_DATASETS", "00_serving_sales,00_serving_inventory,00_serving_operation"
        ).split(",")
        if d.strip()
    ]
    # Preview luôn chạy qua execution.bq_client.execute() (ORDER BY ưu tiên dòng
    # mới nhất/ít NULL nhất — xem datasource/preview.py), giới hạn bytes riêng nhỏ
    # hơn hẳn BQ_MAX_BYTES_BILLED vì chỉ cần vài chục dòng.
    PREVIEW_ROW_LIMIT = int(os.environ.get("PREVIEW_ROW_LIMIT", "20"))
    PREVIEW_MAX_BYTES = int(os.environ.get("PREVIEW_MAX_BYTES", str(200 * 1024 * 1024)))

    SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
    # Chưa có Lark OAuth thật (Phase 9) — dùng header X-Dev-User tạm, mặc định giá trị
    # này khi header vắng mặt. PHẢI thay bằng identity thật trước khi đưa vào dùng thật.
    DEV_USER_FALLBACK = os.environ.get("DEV_USER_FALLBACK", "dev@local")

    # Dashboard Embeds: host file HTML dashboard (AI sinh ra) để nhúng link vào Lark.
    # Bucket GIỮ PRIVATE hoàn toàn — app luôn proxy đọc qua server (auth/deps.get_bq_client
    # kiểu credential riêng của service), browser không bao giờ chạm GCS trực tiếp.
    EMBEDS_GCS_BUCKET = os.environ.get("EMBEDS_GCS_BUCKET", "surya-495408-dashboard-builder-embeds")
    # Email người được phép upload dashboard mới — nhóm nhỏ đã duyệt trước, không
    # mở cho tất cả người đã đăng nhập. So sánh phải normalize .strip().lower().
    UPLOAD_WHITELIST_EMAILS = [
        e.strip().lower()
        for e in os.environ.get("UPLOAD_WHITELIST_EMAILS", "").split(",")
        if e.strip()
    ]
    # Quản lý cao nhất — luôn có sẵn cả 2 role admin/embed (xem app/auth/roles.py),
    # không lưu trong BigQuery vì cần tồn tại NGAY từ đầu để tự cấp quyền cho người
    # khác qua /admin.html (nếu để trong DB sẽ bị "trứng-gà": không ai cấp được
    # role admin đầu tiên). Mặc định gồm ngadt@hapas.vn — người yêu cầu tính năng này.
    SUPER_ADMIN_EMAILS = [
        e.strip().lower()
        for e in os.environ.get("SUPER_ADMIN_EMAILS", "ngadt@hapas.vn").split(",")
        if e.strip()
    ]
    EMBED_MAX_HTML_BYTES = int(os.environ.get("EMBED_MAX_HTML_BYTES", str(2 * 1024 * 1024)))
    # File dữ liệu (Excel/CSV) user tự tải lên làm nguồn "dữ liệu sống" thay BigQuery —
    # thường lớn hơn hẳn file HTML nên cap riêng, mặc định 10MB.
    EMBED_MAX_DATA_FILE_BYTES = int(os.environ.get("EMBED_MAX_DATA_FILE_BYTES", str(10 * 1024 * 1024)))
    # Ngưỡng bytes riêng cho query sống của embed (khác BQ_MAX_BYTES_BILLED chung) vì
    # đây là endpoint PUBLIC không cần đăng nhập — 1 link lộ ra ngoài không được phép
    # kéo theo chi phí BigQuery lớn. execution.bq_client.execute() enforce ngưỡng này.
    EMBED_DATA_MAX_BYTES_BILLED = int(os.environ.get("EMBED_DATA_MAX_BYTES_BILLED", str(200 * 1024 * 1024)))
    # Cache kết quả query sống trong process theo embed_id — dashboard chỉ load lại
    # lúc mở trang/bấm refresh (không tự poll), cache này chỉ để tránh nhiều người
    # mở cùng lúc làm tốn BigQuery lặp lại vô ích.
    EMBED_DATA_CACHE_TTL_SECONDS = int(os.environ.get("EMBED_DATA_CACHE_TTL_SECONDS", "300"))
