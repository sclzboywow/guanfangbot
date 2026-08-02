from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import bots, events, group_moderation, group_verification, library_delivery, qqbot
from app.services.log_retention import install_log_retention

settings = get_settings()
install_log_retention()
app = FastAPI(title="QQ Bot Admin Starter API", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


app.include_router(bots.router, prefix="/api")
app.include_router(qqbot.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(group_verification.router, prefix="/api")
app.include_router(group_moderation.router, prefix="/api")
app.include_router(library_delivery.router, prefix="/api")
