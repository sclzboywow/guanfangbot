from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.models.schemas import OpenApiRequest
from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.bot_repository import bot_repository
from app.services.qqbot_client import client_manager

router = APIRouter(prefix="/qqbot", tags=["qqbot"])


@router.get("/credential-status")
async def credential_status(
    bot_id: str | None = Query(default=None),
    user: AuthUser = Depends(require_user),
) -> dict[str, object]:
    settings = get_settings()
    include_all = str(user.get("role") or "") == "admin"
    if not bot_id:
        bots = bot_repository.list(
            owner_user_id=None if include_all else str(user["id"]),
            include_all=include_all,
        )
        configured = sum(1 for bot in bots if bot.has_secret and bot.app_id)
        return {
            "mode": "per-bot",
            "configured": configured > 0,
            "configured_count": configured,
            "total_bots": len(bots),
            "token_cached": False,
            "api_base": settings.qqbot_api_base,
        }

    bot = require_owned_bot(bot_id, user)

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


@router.post("/openapi")
async def call_openapi(payload: OpenApiRequest, user: AuthUser = Depends(require_user)) -> dict[str, object]:
    require_owned_bot(payload.bot_id, user)
    client = await client_manager.get(payload.bot_id)
    return await client.request(payload.method, payload.path, payload.query, payload.body)
