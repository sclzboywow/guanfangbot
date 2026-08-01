from fastapi import APIRouter, HTTPException

from app.models.schemas import BotCreate, BotPublic, BotUpdate
from app.services.bot_repository import bot_repository
from app.services.qqbot_client import client_manager

router = APIRouter(prefix="/bots", tags=["bots"])


@router.get("", response_model=list[BotPublic])
def list_bots() -> list[BotPublic]:
    return bot_repository.list()


@router.post("", response_model=BotPublic, status_code=201)
def create_bot(payload: BotCreate) -> BotPublic:
    return bot_repository.create(payload)


@router.get("/{bot_id}", response_model=BotPublic)
def get_bot(bot_id: str) -> BotPublic:
    bot = bot_repository.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return bot


@router.patch("/{bot_id}", response_model=BotPublic)
def update_bot(bot_id: str, update: BotUpdate) -> BotPublic:
    bot = bot_repository.update(bot_id, update)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    if update.client_secret is not None or update.app_id is not None:
        client_manager.drop(bot_id)
    return bot


@router.delete("/{bot_id}")
def delete_bot(bot_id: str) -> dict[str, bool]:
    ok = bot_repository.delete(bot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="机器人不存在")
    client_manager.drop(bot_id)
    return {"ok": True}
