#!/usr/bin/env bash
# Deploy Data Explorer (FastAPI app) lên Cloud Run, project surya-495408.
# Chạy từng bước thủ công (chưa có CI), theo đúng convention dashboard-load-proxy.
set -euo pipefail

PROJECT_ID="surya-495408"
REGION="asia-southeast1"
SERVICE_NAME="ai-dashboard-builder"
SA_EMAIL="dashboard-builder@${PROJECT_ID}.iam.gserviceaccount.com"

echo "== Bật các API cần thiết (idempotent) =="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  --project="$PROJECT_ID"

echo "== Deploy Cloud Run service (build từ Dockerfile qua Cloud Build) =="
# --allow-unauthenticated: BẮT BUỘC vì Lark OAuth redirect đưa trình duyệt user
# (không có Google IAM token) thẳng tới /auth/lark/callback — Cloud Run IAM sẽ chặn
# request đó ở tầng hạ tầng trước khi app kịp nhận nếu để --no-allow-unauthenticated
# (đã gặp lỗi 403 "Forbidden ... does not have permission" thật khi test, đúng nguyên
# nhân này). Gác cổng thật sự chuyển hẳn sang tầng app: mọi /api/* đều bắt buộc session
# Lark OAuth hợp lệ (xem app/auth/deps.py) — KHÔNG set ALLOW_DEV_USER_HEADER ở đây, để
# mặc định tắt cửa hậu X-Dev-User trên production (chỉ bật tay khi dev cục bộ).
#
# --timeout=540s (9 phút): mặc định 60s từng gây lỗi 504 thật khi Planner/Builder cần
# nhiều lượt gọi LLM (vd build blueprint nhiều KPI, hoặc validator retry) — quan sát
# thực tế có request mất 100-150s+. 540s đủ dư cho worst-case (Planner + Builder
# MAX_RETRIES=2). Đây KHÔNG phải fix triệt để (vẫn đồng bộ request/response, user vẫn
# phải đợi) — fix đúng bài là chuyển sang xử lý bất đồng bộ (job + polling/SSE), để
# dành cho lần cải tiến sau.
#
# --memory=1Gi: 512Mi mặc định ban đầu gây OOM-kill thật trên production (log ghi
# nhận 536-558 MiB dùng, vượt hạn mức) — mỗi lượt gọi LLM spawn thêm 1 tiến trình
# Node.js (Claude Agent SDK CLI) chạy song song với Python trong cùng container,
# cộng dồn vượt 512Mi dễ dàng.
# "^;^" đổi delimiter của --set-env-vars từ dấu phẩy sang chấm phẩy — SERVING_DATASETS
# tự nó chứa dấu phẩy (danh sách dataset), để mặc định gcloud sẽ tách nhầm thành nhiều
# biến môi trường rác.
gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --service-account="$SA_EMAIL" \
  --allow-unauthenticated \
  --memory=1Gi \
  --timeout=540s \
  --max-instances=5 \
  --set-env-vars="^;^GCP_PROJECT=${PROJECT_ID};GCP_REGION=${REGION};BQ_APP_DATASET=12_data_agent_log;BQ_APP_TABLE_PREFIX=raw_dashboard_builder_;CATALOG_GCS_BUCKET=surya-495408-dashboard-builder-catalog;SERVING_DATASETS=00_serving_sales,00_serving_inventory,00_serving_operation;LARK_BASE_TOKEN=AcITbzsvraObhisDdQXlO6tggkd;LARK_TABLE_CATALOG_ID=tblA61jccZSexp2F;LARK_TABLE_KPI_ID=tblNr2LJO47ClgWW;LARK_OAUTH_HOST=https://open.larksuite.com;CLAUDE_MODEL=claude-sonnet-5;LARK_APP_ID=${LARK_APP_ID:?Set LARK_APP_ID env var trước khi chạy (không phải secret nhưng cũng không nên hardcode trong script commit lên git)}" \
  --set-secrets="CLAUDE_CODE_OAUTH_TOKEN=dashboard-builder-claude-code-oauth-token:latest,LARK_APP_SECRET=dashboard-builder-lark-app-secret:latest,SESSION_SECRET=dashboard-builder-session-secret:latest"

echo "== Xong. URL service (public ở tầng mạng, gác cổng bằng Lark OAuth ở tầng app): =="
gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format="value(status.url)"

echo ""
echo "== Test cục bộ (bypass Lark OAuth, chỉ dùng máy dev): =="
echo "Thêm ALLOW_DEV_USER_HEADER=true vào .env trước khi chạy uvicorn cục bộ."
