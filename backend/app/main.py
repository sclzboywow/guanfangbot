from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import bots, events, group_verification, qqbot

settings = get_settings()
app = FastAPI(title="QQ Bot Admin Starter API", version="0.2.0")
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
