from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.routers import (
    ai,
    auth,
    bots,
    chat,
    events,
    group_management,
    group_moderation,
    group_verification,
    library_delivery,
    qqbot,
)
from app.services.ai_reply_service import ai_reply_service
from app.services.auth_deps import get_optional_user
from app.services.bootstrap import bootstrap_auth_and_ownership
from app.services.log_retention import install_log_retention

settings = get_settings()

PUBLIC_PATHS = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/events/callback"),
}


def _is_public(method: str, path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if (method, normalized) in PUBLIC_PATHS:
        return True
    if method == "POST" and normalized.startswith("/api/events/callback/"):
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        if method == "OPTIONS":
            return await call_next(request)
        if path.startswith("/api/") and not _is_public(method, path):
            if get_optional_user(request) is None:
                return JSONResponse({"detail": "未登录"}, status_code=401)
        return await call_next(request)


@asynccontextmanager
async def lifespan(_: FastAPI):
    install_log_retention()
    bootstrap_auth_and_ownership()
    await ai_reply_service.start()
    try:
        yield
    finally:
        await ai_reply_service.stop()


app = FastAPI(
    title="QQ Bot Admin Starter API",
    version="0.7.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


app.include_router(auth.router, prefix="/api")
app.include_router(bots.router, prefix="/api")
app.include_router(qqbot.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(group_management.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(group_verification.router, prefix="/api")
app.include_router(group_moderation.router, prefix="/api")
app.include_router(library_delivery.router, prefix="/api")
