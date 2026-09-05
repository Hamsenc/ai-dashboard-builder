"""API duyệt bảng + xem trước dữ liệu — thay cho luồng dashboard builder cũ
(blueprint/build/render). Không sinh SQL, không tính KPI, chỉ chiếu metadata +
vài chục dòng dữ liệu thật để user tự hiểu dữ liệu công ty đang có trước khi tự
đi dựng báo cáo ở nơi khác.

3 route bên dưới khai báo `def` thường (KHÔNG `async def`): thân hàm chỉ toàn
lời gọi BigQuery/bq_store đồng bộ, không có `await` nào — để `async def` sẽ chạy
thẳng trên event loop và ĐÓNG BĂNG toàn bộ server (mọi request khác) trong lúc
chờ BigQuery trả lời vài giây. FastAPI/Starlette tự đưa route `def` thường vào
thread pool riêng, đúng cơ chế dành cho code I/O đồng bộ như thế này."""

from __future__ import annotations

from auth.deps import get_current_user
from config import Config
from datasource import bq_meta, preview
from fastapi import APIRouter, Depends, HTTPException
from google.cloud import bigquery
from storage import bq_store

router = APIRouter(prefix="/api/tables")

# 1 client dùng chung cho cả process — bigquery.Client thread-safe (an toàn để
# nhiều thread pool worker dùng chung), tạo mới mỗi request tốn thêm 1 vòng
# discovery credentials/project vô ích.
_client: bigquery.Client | None = None


def get_bq_client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client()
    return _client


@router.get("")
def list_tables(user: str = Depends(get_current_user)):
    client = get_bq_client()
    tables = bq_meta.list_tables(client)
    return {"tables": tables}


@router.get("/{table_id}")
def get_table_detail(table_id: str, user: str = Depends(get_current_user)):
    client = get_bq_client()
    try:
        table = bq_meta.get_table(client, table_id)
    except bq_meta.OutOfScopeError as e:
        raise HTTPException(403, str(e)) from e
    if table is None:
        raise HTTPException(404, f"Không tìm thấy bảng '{table_id}' trong phạm vi Serving.")

    bq_store.insert_data_access(client, created_by=user, table_id=table_id, action="view_detail")
    return table


@router.get("/{table_id}/preview")
def preview_table(table_id: str, limit: int = Config.PREVIEW_ROW_LIMIT, user: str = Depends(get_current_user)):
    client = get_bq_client()
    try:
        result = preview.preview_rows(client, table_id, limit=limit)
    except bq_meta.OutOfScopeError as e:
        raise HTTPException(403, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e

    bq_store.insert_data_access(
        client, created_by=user, table_id=table_id, action="preview", row_count=len(result["rows"])
    )
    return result
