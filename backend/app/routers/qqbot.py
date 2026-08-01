from fastapi import APIRouter, Query

from app.config import get_settings
from app.models.schemas import OpenApiRequest
from app.services.bot_repository import bot_repository
from app.services.qqbot_client import client_manager

router = APIRouter(prefix="/qqbot", tags=["qqbot"])


@router.get("/credential-status")
async def credential_status(bot_id: str | None = Query(default=None)) -> dict[str, object]:
    settings = get_settings()
    if not bot_id:
        bots = bot_repository.list()
        configured = sum(1 for bot in bots if bot.has_secret and bot.app_id)
        return {
            "mode": "per-bot",
            "configured": configured > 0,
            "configured_count": configured,
            "total_bots": len(bots),
            "token_cached": False,
            "api_base": settings.qqbot_api_base,
        }

    bot = bot_repository.get(bot_id)
    if bot is None:
        return {
            "mode": "per-bot",
            "bot_id": bot_id,
            "configured": False,
            "token_cached": False,
            "api_base": settings.qqbot_api_base,
            "detail": "机器人不存在",
        }

    token_cached = False
    if bot.has_secret and bot.app_id:
        try:
            client = await client_manager.get(bot_id)
            token_cached = client.token_cached
        except Exception:
            token_cached = False

    return {
        "mode": "per-bot",
        "bot_id": bot_id,
        "configured": bool(bot.has_secret and bot.app_id),
        "token_cached": token_cached,
        "api_base": settings.qqbot_api_base,
        "app_id": bot.app_id,
    }


@router.post("/token/refresh")
async def refresh_token(bot_id: str = Query(...)) -> dict[str, object]:
    client = await client_manager.get(bot_id)
    _, expires_in = await client.get_access_token(force=True)
    return {"ok": True, "bot_id": bot_id, "expires_in": expires_in}


@router.post("/openapi")
async def call_openapi(payload: OpenApiRequest) -> dict[str, object]:
    client = await client_manager.get(payload.bot_id)
    return await client.request(payload.method, payload.path, payload.query, payload.body)
