from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.models.schemas import BotUpdate, GroupVerificationSettingsUpdate
from app.services.bot_repository import bot_repository
from app.services.group_verification_repository import group_verification_repository
from app.services.group_verification_service import REQUIRED_EVENTS, group_verification_service

router = APIRouter(prefix="/group-verification", tags=["group-verification"])


def _require_bot(bot_id: str):
    bot = bot_repository.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return bot


def _status_payload(bot_id: str) -> dict[str, Any]:
    bot = _require_bot(bot_id)
    configured = set(bot.event_scopes)
    return {
        "bot_id": bot.id,
        "app_id": bot.app_id,
        "bot_name": bot.name,
        "settings": group_verification_repository.get_settings(bot_id),
        "required_events": [
            {"code": code, "configured": code in configured}
            for code in REQUIRED_EVENTS
        ],
        "requirements_ready": all(code in configured for code in REQUIRED_EVENTS),
        "counts": group_verification_repository.counts(bot_id),
        "sessions": group_verification_repository.list_sessions(bot_id),
        "logs": group_verification_repository.list_logs(bot_id, limit=80),
        "behavior": {
            "answer_requires_at": False,
            "pending_messages_retracted": True,
            "verification_expires": False,
            "outbound_messages_single_line": True,
        },
    }


@router.get("/status")
def verification_status(bot_id: str) -> dict[str, Any]:
    return _status_payload(bot_id)


@router.put("/settings/{bot_id}")
def update_verification_settings(
    bot_id: str,
    payload: GroupVerificationSettingsUpdate,
) -> dict[str, Any]:
    bot = _require_bot(bot_id)
    if payload.enabled:
        selected = list(dict.fromkeys([*bot.event_scopes, *REQUIRED_EVENTS]))
        bot_repository.update(bot_id, BotUpdate(event_scopes=selected))
    group_verification_repository.update_settings(
        bot_id,
        enabled=payload.enabled,
        min_operand=payload.min_operand,
        max_operand=payload.max_operand,
    )
    return _status_payload(bot_id)


@router.post("/sessions/{session_id}/verify")
async def manual_verify(session_id: str) -> dict[str, Any]:
    session = group_verification_repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="验证记录不存在")
    try:
        await group_verification_service.verify_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _status_payload(str(session["bot_id"]))


@router.post("/sessions/{session_id}/reset")
async def reset_verification(session_id: str) -> dict[str, Any]:
    session = group_verification_repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="验证记录不存在")
    try:
        await group_verification_service.reset_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _status_payload(str(session["bot_id"]))


@router.post("/sessions/{session_id}/close")
def close_verification(session_id: str) -> dict[str, Any]:
    session = group_verification_repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="验证记录不存在")
    group_verification_repository.close_session(session_id)
    group_verification_repository.add_log(
        bot_id=str(session["bot_id"]),
        session_id=session_id,
        action="manual_close",
        success=True,
    )
    return _status_payload(str(session["bot_id"]))
