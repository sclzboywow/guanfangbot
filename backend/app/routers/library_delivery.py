from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.models.schemas import BotUpdate, LibraryDeliverySettingsUpdate, LibrarySearchTestRequest
from app.services.baidu_oauth_service import BaiduOAuthError, baidu_oauth_service
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
        "oauth": baidu_oauth_service.public_status(),
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
            "baidu_account_scope": "single_backend_account",
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


@router.post("/oauth/start")
async def start_baidu_oauth(bot_id: str = Query(...)) -> dict[str, Any]:
    _require_bot(bot_id)
    try:
        session = await baidu_oauth_service.start_authorization(bot_id)
    except BaiduOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"oauth": baidu_oauth_service.public_status(), "session": session}


@router.post("/oauth/poll/{session_id}")
async def poll_baidu_oauth(session_id: str) -> dict[str, Any]:
    try:
        session = await baidu_oauth_service.poll_authorization(session_id)
    except BaiduOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"oauth": baidu_oauth_service.public_status(), "session": session}


@router.get("/oauth/qr/{session_id}")
async def baidu_oauth_qr(session_id: str) -> Response:
    try:
        content, content_type = await baidu_oauth_service.fetch_qr_image(session_id)
    except BaiduOAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "no-store, max-age=0", "X-Content-Type-Options": "nosniff"},
    )
