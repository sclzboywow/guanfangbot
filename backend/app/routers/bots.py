from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import BotCreate, BotPublic, BotUpdate
from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.bot_repository import bot_repository
from app.services.qqbot_client import client_manager

router = APIRouter(prefix="/bots", tags=["bots"])


async def _sync_profile(bot_id: str) -> BotPublic:
    client = await client_manager.get(bot_id)
    me = await client.fetch_me()
    name = str(me.get("username") or "").strip()
    avatar_url = str(me.get("avatar") or "").strip()
    bot = bot_repository.set_profile(bot_id, name=name or None, avatar_url=avatar_url)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return bot


@router.get("", response_model=list[BotPublic])
def list_bots(user: AuthUser = Depends(require_user)) -> list[BotPublic]:
    include_all = str(user.get("role") or "") == "admin"
    return bot_repository.list(
        owner_user_id=None if include_all else str(user["id"]),
        include_all=include_all,
    )


@router.post("", response_model=BotPublic, status_code=201)
async def create_bot(payload: BotCreate, user: AuthUser = Depends(require_user)) -> BotPublic:
    try:
        bot = bot_repository.create(payload, owner_user_id=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        return await _sync_profile(bot.id)
    except HTTPException as exc:
        # Roll back invalid credentials so the list stays clean.
        bot_repository.delete(bot.id)
        client_manager.drop(bot.id)
        raise HTTPException(status_code=exc.status_code, detail=f"凭证校验失败：{exc.detail}") from exc


@router.get("/{bot_id}", response_model=BotPublic)
def get_bot(bot_id: str, user: AuthUser = Depends(require_user)) -> BotPublic:
    return require_owned_bot(bot_id, user)


@router.patch("/{bot_id}", response_model=BotPublic)
async def update_bot(bot_id: str, update: BotUpdate, user: AuthUser = Depends(require_user)) -> BotPublic:
    require_owned_bot(bot_id, user)
    try:
        bot = bot_repository.update(bot_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    if update.client_secret is not None or update.app_id is not None:
        client_manager.drop(bot_id)
        return await _sync_profile(bot_id)
    return bot


@router.post("/{bot_id}/sync-profile", response_model=BotPublic)
async def sync_bot_profile(bot_id: str, user: AuthUser = Depends(require_user)) -> BotPublic:
    require_owned_bot(bot_id, user)
    return await _sync_profile(bot_id)


@router.delete("/{bot_id}")
def delete_bot(bot_id: str, user: AuthUser = Depends(require_user)) -> dict[str, bool]:
    require_owned_bot(bot_id, user)
    ok = bot_repository.delete(bot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="机器人不存在")
    client_manager.drop(bot_id)
    return {"ok": True}
