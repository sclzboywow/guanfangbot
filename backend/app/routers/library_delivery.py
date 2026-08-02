from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import BotUpdate, LibraryDeliverySettingsUpdate, LibrarySearchTestRequest
from app.services.bot_repository import bot_repository
from app.services.library_catalog import LibraryCatalogError, inspect_catalog, search_catalog
from app.services.library_delivery_repository import library_delivery_repository
from app.services.library_delivery_service import REQUIRED_EVENTS

router = APIRouter(prefix="/library-delivery", tags=["library-delivery"])


def _require_bot(bot_id: str):
    bot = bot_repository.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return bot


def _database_status(settings: dict[str, Any]) -> dict[str, Any]:
    private = library_delivery_repository.get_private_settings(str(settings["bot_id"]))
    try:
        result = inspect_catalog(private)
        return {"ready": True, "error": "", **result}
    except LibraryCatalogError as exc:
        return {"ready": False, "row_count": 0, "columns": [], "error": str(exc)}


def _status_payload(bot_id: str) -> dict[str, Any]:
    bot = _require_bot(bot_id)
    settings = library_delivery_repository.get_public_settings(bot_id)
    configured = set(bot.event_scopes)
    return {
        "bot_id": bot.id,
        "app_id": bot.app_id,
        "bot_name": bot.name,
        "settings": settings,
        "database": _database_status(settings),
        "required_events": [
            {"code": code, "configured": code in configured}
            for code in REQUIRED_EVENTS
        ],
        "requirements_ready": all(code in configured for code in REQUIRED_EVENTS),
        "counts": library_delivery_repository.counts(bot_id),
        "logs": library_delivery_repository.list_logs(bot_id),
        "behavior": {
            "search_requires_at": True,
            "selection_requires_at": False,
            "max_results": 5,
            "session_one_use": True,
            "outbound_messages_single_line": True,
        },
    }


@router.get("/status")
def library_delivery_status(bot_id: str = Query(...)) -> dict[str, Any]:
    return _status_payload(bot_id)


@router.put("/settings/{bot_id}")
def update_library_delivery_settings(
    bot_id: str,
    payload: LibraryDeliverySettingsUpdate,
) -> dict[str, Any]:
    bot = _require_bot(bot_id)
    if payload.enabled:
        selected = list(dict.fromkeys([*bot.event_scopes, *REQUIRED_EVENTS]))
        bot_repository.update(bot_id, BotUpdate(event_scopes=selected))
    library_delivery_repository.update_settings(bot_id, **payload.model_dump())
    return _status_payload(bot_id)


@router.post("/test-search")
def test_library_search(payload: LibrarySearchTestRequest) -> dict[str, Any]:
    _require_bot(payload.bot_id)
    settings = library_delivery_repository.get_private_settings(payload.bot_id)
    try:
        total, results = search_catalog(settings, payload.keyword, limit=5)
    except LibraryCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"keyword": payload.keyword, "total_count": total, "results": results}
