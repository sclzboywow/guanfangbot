from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.schemas import BotUpdate, GroupModerationSettingsUpdate
from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.bot_repository import bot_repository
from app.services.group_moderation_repository import group_moderation_repository
from app.services.group_moderation_service import REQUIRED_EVENTS, group_moderation_service

router = APIRouter(prefix="/group-moderation", tags=["group-moderation"])


def _require_member(member_id: str) -> dict[str, Any]:
    member = group_moderation_repository.get_member_by_id(member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="治理成员不存在")
    return member


def _status_payload(bot_id: str, user: AuthUser) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    configured = set(bot.event_scopes)
    return {
        "bot_id": bot.id,
        "app_id": bot.app_id,
        "bot_name": bot.name,
        "settings": group_moderation_repository.get_settings(bot_id),
        "required_events": [
            {"code": code, "configured": code in configured}
            for code in REQUIRED_EVENTS
        ],
        "requirements_ready": all(code in configured for code in REQUIRED_EVENTS),
        "counts": group_moderation_repository.counts(bot_id),
        "members": group_moderation_repository.list_members(bot_id),
        "logs": group_moderation_repository.list_logs(bot_id),
        "behavior": {
            "warning_before_penalty": True,
            "blocked_messages_retracted": True,
            "official_mute_enabled": bool(group_moderation_repository.get_settings(bot_id).get("use_official_mute", True)),
            "outbound_messages_single_line": True,
            "scope": "bot_group_member",
        },
    }


@router.get("/status")
def moderation_status(bot_id: str = Query(...), user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return _status_payload(bot_id, user)


@router.put("/settings/{bot_id}")
def update_moderation_settings(
    bot_id: str,
    payload: GroupModerationSettingsUpdate,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    if payload.enabled:
        selected = list(dict.fromkeys([*bot.event_scopes, *REQUIRED_EVENTS]))
        bot_repository.update(bot_id, BotUpdate(event_scopes=selected))
    group_moderation_repository.update_settings(bot_id, **payload.model_dump())
    return _status_payload(bot_id, user)


@router.post("/members/{member_id}/release")
async def release_member(
    member_id: str,
    reset_strikes: bool = Query(default=False),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    member = _require_member(member_id)
    require_owned_bot(str(member["bot_id"]), user)
    settings = group_moderation_repository.get_settings(str(member["bot_id"]))
    if settings.get("use_official_mute", True):
        await group_moderation_service.set_official_mute(
            str(member["bot_id"]),
            str(member["group_openid"]),
            str(member["member_openid"]),
            op="del",
            member_id=member_id,
            rule="manual_release",
        )
    group_moderation_repository.release_member(member_id, reset_strikes=reset_strikes)
    group_moderation_repository.add_log(
        bot_id=str(member["bot_id"]), member_id=member_id,
        group_openid=str(member["group_openid"]), member_openid=str(member["member_openid"]),
        action="manual_release_reset" if reset_strikes else "manual_release", success=True,
    )
    return _status_payload(str(member["bot_id"]), user)


@router.post("/members/{member_id}/permanent")
async def make_member_permanent(member_id: str, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    member = _require_member(member_id)
    require_owned_bot(str(member["bot_id"]), user)
    settings = group_moderation_repository.get_settings(str(member["bot_id"]))
    if settings.get("use_official_mute", True):
        durations = [int(value) for value in settings.get("penalty_minutes", []) if int(value) > 0]
        renewal_minutes = durations[-1] if durations else 10080
        await group_moderation_service.set_official_mute(
            str(member["bot_id"]),
            str(member["group_openid"]),
            str(member["member_openid"]),
            op="add",
            mute_expire_at=(datetime.now(timezone.utc) + timedelta(minutes=renewal_minutes)).isoformat(),
            member_id=member_id,
            rule="manual_permanent",
        )
    group_moderation_repository.make_permanent(member_id)
    group_moderation_repository.add_log(
        bot_id=str(member["bot_id"]), member_id=member_id,
        group_openid=str(member["group_openid"]), member_openid=str(member["member_openid"]),
        action="manual_permanent", success=True,
    )
    return _status_payload(str(member["bot_id"]), user)


@router.post("/members/{member_id}/trust")
async def trust_member(member_id: str, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    member = _require_member(member_id)
    require_owned_bot(str(member["bot_id"]), user)
    settings = group_moderation_repository.get_settings(str(member["bot_id"]))
    if settings.get("use_official_mute", True):
        await group_moderation_service.set_official_mute(
            str(member["bot_id"]),
            str(member["group_openid"]),
            str(member["member_openid"]),
            op="del",
            member_id=member_id,
            rule="manual_trust",
        )
    group_moderation_repository.set_trusted(member_id, True)
    group_moderation_repository.add_log(
        bot_id=str(member["bot_id"]), member_id=member_id,
        group_openid=str(member["group_openid"]), member_openid=str(member["member_openid"]),
        action="manual_trust", success=True,
    )
    return _status_payload(str(member["bot_id"]), user)


@router.post("/members/{member_id}/untrust")
def untrust_member(member_id: str, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    member = _require_member(member_id)
    require_owned_bot(str(member["bot_id"]), user)
    group_moderation_repository.set_trusted(member_id, False)
    group_moderation_repository.add_log(
        bot_id=str(member["bot_id"]), member_id=member_id,
        group_openid=str(member["group_openid"]), member_openid=str(member["member_openid"]),
        action="manual_untrust", success=True,
    )
    return _status_payload(str(member["bot_id"]), user)
