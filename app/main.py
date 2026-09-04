"""FastAPI app: chat + blueprint + dashboard API + Lark OAuth, phục vụ luôn static
SPA ở /."""

from __future__ import annotations

import pathlib

from api import blueprint, chat, dashboard
from auth import lark_oauth
from auth.deps import get_current_user
from catalog.client import load_catalog
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="AI Dashboard Builder")

app.include_router(chat.router)
app.include_router(blueprint.router)
app.include_router(dashboard.router)
app.include_router(lark_oauth.router)


@app.get("/api/me")
async def get_me(request: Request, user: str = Depends(get_current_user)):
    is_lark_session = request.cookies.get("session") is not None
    return {"user": user, "authenticated_via_lark": is_lark_session}


@app.on_event("startup")
async def warm_catalog_cache() -> None:
    # Không chặn app khởi động nếu GCS/catalog lỗi — lỗi sẽ nổi lên rõ ràng ở lần
    # gọi /api/chat/message đầu tiên thay vì làm cả service down.
    try:
        load_catalog()
    except Exception as e:  # noqa: BLE001
        print(f"CẢNH BÁO: không load được catalog lúc khởi động: {e}")


_web_dir = pathlib.Path(__file__).resolve().parent / "web"
app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
