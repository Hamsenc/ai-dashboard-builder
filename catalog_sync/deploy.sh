#!/usr/bin/env bash
# Deploy catalog_sync như Cloud Run Job + Cloud Scheduler (chạy hằng ngày 3h sáng
# giờ VN). Job này KHÔNG gọi Claude (không cần CLAUDE_CODE_OAUTH_TOKEN) — chỉ đọc
# Lark + BigQuery INFORMATION_SCHEMA, ghi catalog JSON lên GCS.
set -euo pipefail

PROJECT_ID="surya-495408"
REGION="asia-southeast1"
JOB_NAME="dashboard-builder-catalog-sync"
SA_EMAIL="dashboard-builder@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB_NAME="dashboard-builder-catalog-sync-daily"

echo "== Bật API cần thiết =="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  --project="$PROJECT_ID"

echo "== Build + deploy Cloud Run Job (chạy script này từ trong thư mục catalog_sync/) =="
gcloud run jobs deploy "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --service-account="$SA_EMAIL" \
  --memory=512Mi \
  --task-timeout=300s \
  --max-retries=1 \
  --set-env-vars="GCP_PROJECT=${PROJECT_ID},BQ_APP_DATASET=12_data_agent_log,BQ_APP_TABLE_PREFIX=raw_dashboard_builder_,CATALOG_GCS_BUCKET=surya-495408-dashboard-builder-catalog,LARK_BASE_TOKEN=AcITbzsvraObhisDdQXlO6tggkd,LARK_OAUTH_HOST=https://open.larksuite.com,TRIGGERED_BY=cloud_scheduler,LARK_APP_ID=${LARK_APP_ID:?Set LARK_APP_ID env var trước khi chạy}" \
  --set-secrets="LARK_APP_SECRET=dashboard-builder-lark-app-secret:latest"

echo "== Cấp quyền cho chính SA này gọi Cloud Run Jobs execute API (Scheduler chạy dưới danh nghĩa SA) =="
gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

echo "== Tạo/cập nhật Cloud Scheduler (0 3 * * *, Asia/Ho_Chi_Minh) =="
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"
if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    --project="$PROJECT_ID" --location="$REGION" \
    --schedule="0 3 * * *" --time-zone="Asia/Ho_Chi_Minh" \
    --uri="$JOB_URI" --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL"
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    --project="$PROJECT_ID" --location="$REGION" \
    --schedule="0 3 * * *" --time-zone="Asia/Ho_Chi_Minh" \
    --uri="$JOB_URI" --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL"
fi

echo "== Xong. Chạy thử ngay (không đợi lịch): =="
echo "gcloud run jobs execute $JOB_NAME --project=$PROJECT_ID --region=$REGION"
