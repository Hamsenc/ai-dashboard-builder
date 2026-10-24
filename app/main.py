"""FastAPI app: Data Explorer (duyệt bảng, xem trước dữ liệu, tư vấn chọn bảng) +
Lark OAuth, phục vụ luôn static SPA ở /."""

from __future__ import annotations

import pathlib

from api import admin, advise, catalog, embed_view, embeds
from auth import lark_oauth
from auth.deps import get_current_user
from auth.roles import can_use_embeds, is_admin
from catalog.client import load_catalog
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Data Explorer")

app.include_router(catalog.router)
app.include_router(advise.router)
app.include_router(lark_oauth.router)
app.include_router(embeds.router)
app.include_router(admin.router)
app.include_router(embed_view.router)  # public, phải đăng ký trước StaticFiles mount bên dưới


@app.get("/api/me")
async def get_me(request: Request, user: str = Depends(get_current_user)):
    is_lark_session = request.cookies.get("session") is not None
    return {
        "user": user,
        "authenticated_via_lark": is_lark_session,
        "can_upload_embed": can_use_embeds(user),
        "is_admin": is_admin(user),
    }


@app.on_event("startup")
async def warm_catalog_cache() -> None:
    # Không chặn app khởi động nếu GCS/catalog lỗi — lỗi sẽ nổi lên rõ ràng ở lần
    # gọi đầu tiên cần tới enrich (bq_meta.enrich_from_lark) thay vì làm cả service
    # down. Catalog Lark giờ chỉ là làm giàu tuỳ chọn, không phải nguồn bắt buộc.
    try:
        load_catalog()
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO: không load được catalog lúc khởi động: {e}")


_web_dir = pathlib.Path(__file__).resolve().parent / "web"
app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
