from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.models.schemas import BotUpdate, LibraryDeliverySettingsUpdate, LibrarySearchTestRequest
from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.baidu_oauth_service import BaiduOAuthError, baidu_oauth_service
from app.services.bot_repository import bot_repository
from app.services.library_catalog import LibraryCatalogError, inspect_catalog, search_catalog
from app.services.library_delivery_repository import library_delivery_repository
from app.services.library_delivery_service import REQUIRED_EVENTS

router = APIRouter(prefix="/library-delivery", tags=["library-delivery"])


def _owner_id(bot_id: str) -> str:
    owner = bot_repository.get_owner_user_id(bot_id)
    if not owner:
        raise HTTPException(status_code=400, detail="机器人尚未归属用户")
    return owner


def _database_status(settings: dict[str, Any]) -> dict[str, Any]:
    private = library_delivery_repository.get_private_settings(str(settings["bot_id"]))
    try:
        result = inspect_catalog(private)
        return {"ready": True, "error": "", **result}
    except LibraryCatalogError as exc:
        return {"ready": False, "row_count": 0, "columns": [], "error": str(exc)}


def _status_payload(bot_id: str, user: AuthUser) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    settings = library_delivery_repository.get_public_settings(bot_id)
    configured = set(bot.event_scopes)
    owner_user_id = _owner_id(bot_id)
    return {
        "bot_id": bot.id,
        "app_id": bot.app_id,
        "bot_name": bot.name,
        "settings": settings,
        "oauth": baidu_oauth_service.public_status(owner_user_id),
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
            "outbound_messages_single_line": False,
            "search_and_share_messages_multiline": True,
            "baidu_account_scope": "per_owner_user",
        },
    }


@router.get("/status")
def library_delivery_status(bot_id: str = Query(...), user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return _status_payload(bot_id, user)


@router.put("/settings/{bot_id}")
def update_library_delivery_settings(
    bot_id: str,
    payload: LibraryDeliverySettingsUpdate,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    if payload.enabled:
        selected = list(dict.fromkeys([*bot.event_scopes, *REQUIRED_EVENTS]))
        bot_repository.update(bot_id, BotUpdate(event_scopes=selected))
    library_delivery_repository.update_settings(bot_id, **payload.model_dump(exclude_unset=True))
    return _status_payload(bot_id, user)


@router.post("/test-search")
def test_library_search(
    payload: LibrarySearchTestRequest,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(payload.bot_id, user)
    settings = library_delivery_repository.get_private_settings(payload.bot_id)
    try:
        total, results = search_catalog(settings, payload.keyword, limit=5)
    except LibraryCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"keyword": payload.keyword, "total_count": total, "results": results}


@router.post("/oauth/start")
async def start_baidu_oauth(
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    owner_user_id = _owner_id(bot_id)
    try:
        session = await baidu_oauth_service.start_authorization(bot_id, owner_user_id)
    except BaiduOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"oauth": baidu_oauth_service.public_status(owner_user_id), "session": session}


@router.post("/oauth/poll/{session_id}")
async def poll_baidu_oauth(session_id: str, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    session_row = baidu_oauth_service.repository.get_session(session_id)
    if session_row is None:
        raise HTTPException(status_code=404, detail="授权会话不存在")
    bot_id = str(session_row.get("requested_by_bot_id") or "")
    require_owned_bot(bot_id, user)
    owner_user_id = str(session_row.get("owner_user_id") or _owner_id(bot_id))
    try:
        session = await baidu_oauth_service.poll_authorization(session_id)
    except BaiduOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"oauth": baidu_oauth_service.public_status(owner_user_id), "session": session}


@router.get("/oauth/qr/{session_id}")
async def baidu_oauth_qr(session_id: str, user: AuthUser = Depends(require_user)) -> Response:
    session_row = baidu_oauth_service.repository.get_session(session_id)
    if session_row is None:
        raise HTTPException(status_code=404, detail="授权会话不存在")
    require_owned_bot(str(session_row.get("requested_by_bot_id") or ""), user)
    try:
        content, content_type = await baidu_oauth_service.fetch_qr_image(session_id)
    except BaiduOAuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "no-store, max-age=0", "X-Content-Type-Options": "nosniff"},
    )
