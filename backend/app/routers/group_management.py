from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.schemas import (
    ApprovalStrategyCreate,
    ApprovalStrategyUpdate,
    ApprovalWhitelistUpdate,
    BotUpdate,
    GroupManagementSettingsUpdate,
    OfficialJoinDecision,
    OfficialMuteUpdate,
)
from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.bot_repository import bot_repository
from app.services.group_management_repository import group_management_repository
from app.services.group_management_service import REQUIRED_EVENTS, group_management_service
from app.services.group_moderation_repository import group_moderation_repository
from app.services.group_mute_service import group_mute_coordinator
from app.services.group_verification_repository import group_verification_repository


router = APIRouter(prefix="/group-management", tags=["group-management"])


def _merge_known_member(
    store: dict[tuple[str, str], dict[str, str]],
    *,
    group_openid: str,
    member_openid: str,
    username: str = "",
    last_seen_at: str = "",
) -> None:
    group_openid = str(group_openid or "").strip()
    member_openid = str(member_openid or "").strip()
    if not group_openid or not member_openid:
        return
    key = (group_openid, member_openid)
    current = store.get(key, {})
    name = str(username or "").strip() or str(current.get("username") or "").strip()
    seen = str(last_seen_at or "").strip() or str(current.get("last_seen_at") or "").strip()
    store[key] = {
        "group_openid": group_openid,
        "member_openid": member_openid,
        "username": name,
        "last_seen_at": seen,
    }


def _status(bot_id: str, user: AuthUser) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    configured = set(bot.event_scopes)
    known_members: dict[tuple[str, str], dict[str, str]] = {}
    for item in group_management_repository.known_members(bot_id):
        _merge_known_member(
            known_members,
            group_openid=str(item.get("group_openid") or ""),
            member_openid=str(item.get("member_openid") or ""),
            username=str(item.get("username") or ""),
            last_seen_at=str(item.get("last_seen_at") or ""),
        )
    for session in group_verification_repository.list_sessions(bot_id, limit=1000):
        _merge_known_member(
            known_members,
            group_openid=str(session.get("group_openid") or ""),
            member_openid=str(session.get("member_openid") or ""),
            username=str(session.get("member_name") or ""),
            last_seen_at=str(session.get("last_message_at") or session.get("joined_at") or ""),
        )
    # Message-moderation already stores author nicknames from GROUP_MESSAGE_CREATE.
    for member in group_moderation_repository.list_members(bot_id, limit=1000):
        _merge_known_member(
            known_members,
            group_openid=str(member.get("group_openid") or ""),
            member_openid=str(member.get("member_openid") or ""),
            username=str(member.get("member_name") or ""),
            last_seen_at=str(member.get("last_message_at") or member.get("updated_at") or ""),
        )
    sorted_members = sorted(
        known_members.values(),
        key=lambda item: str(item.get("last_seen_at") or ""),
        reverse=True,
    )
    return {
        "bot_id": bot.id,
        "app_id": bot.app_id,
        "bot_name": bot.name,
        "required_events": [
            {"code": code, "configured": code in configured}
            for code in REQUIRED_EVENTS
        ],
        "requirements_ready": all(code in configured for code in REQUIRED_EVENTS),
        "settings": group_management_repository.get_settings(bot_id),
        "groups": group_management_repository.list_groups(bot_id),
        "known_members": sorted_members,
        "join_requests": group_management_repository.list_join_requests(bot_id),
        "logs": group_management_repository.list_logs(bot_id, limit=100),
        "ingest": {
            "mode": "event",
            "required_event": "GROUP_JOIN_REQUEST",
            "manual_sync": True,
        },
        "limits": {
            "join_request_qpm": 30,
            "write_qpm": 60,
            "strategy_max": 20,
            "groups_per_strategy": 100,
            "whitelist_per_request": 10000,
            "whitelist_total": 100000,
            "mutes_per_request": 10,
        },
    }


async def _release_manual_mute(bot_id: str, group_openid: str, member_openid: str) -> None:
    """Release only the management-console mute source without clearing verification/moderation mutes."""
    result = await group_mute_coordinator.release(
        bot_id,
        group_openid,
        member_openid,
        source="manual",
    )
    status_code = int(result.get("status_code", 500))
    if status_code >= 300:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "QQ 官方解除禁言失败",
                "qq_status": status_code,
                "qq_data": result.get("data"),
            },
        )

    data = result.get("data")
    untracked_manual_mute = (
        isinstance(data, dict)
        and data.get("message") == "该来源没有有效禁言，无需解除"
        and not bool(result.get("still_muted"))
    )
    if untracked_manual_mute:
        # No local lease exists at all: allow the console to clear an externally-created mute.
        await group_management_service.set_member_mutes(
            bot_id,
            group_openid,
            [{"op": "del", "member_openid": member_openid, "mute_expire_at": ""}],
        )


@router.get("/status")
async def status(bot_id: str = Query(...), user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    # Fill missing group names when opening the page (existing rows often predate /info sync).
    await group_management_service.backfill_missing_group_names(bot_id, limit=15)
    return _status(bot_id, user)


@router.put("/settings/{bot_id}")
async def update_settings(
    bot_id: str,
    payload: GroupManagementSettingsUpdate,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    current = group_management_repository.get_settings(bot_id)
    if current["auto_approval_enabled"] and not payload.auto_approval_enabled:
        await group_management_service.disable_enabled_strategies(bot_id)
    group_management_repository.update_settings(bot_id, **payload.model_dump())
    return _status(bot_id, user)


@router.post("/events/{bot_id}/enable")
def enable_required_events(bot_id: str, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    selected = list(dict.fromkeys([*bot.event_scopes, *REQUIRED_EVENTS]))
    bot_repository.update(bot_id, BotUpdate(event_scopes=selected))
    return _status(bot_id, user)


@router.post("/join-requests/sync")
async def sync_join_requests(
    bot_id: str = Query(...),
    group_openid: str = Query(..., min_length=1, max_length=128),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    sync = await group_management_service.sync_join_requests(bot_id, group_openid)
    return {"sync": sync, "status": _status(bot_id, user)}


@router.post("/join-requests/decision")
async def decide_join_request(
    payload: OfficialJoinDecision,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    result = await group_management_service.decide_join_request(bot_id, **payload.model_dump())
    return {"result": result, "status": _status(bot_id, user)}


@router.get("/mutes")
async def get_mutes(
    bot_id: str = Query(...),
    group_openid: str = Query(..., min_length=1, max_length=128),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.get_mute_setting(bot_id, group_openid)


@router.post("/mutes")
async def set_mutes(
    payload: OfficialMuteUpdate,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    for item in payload.members:
        member = item.model_dump()
        if member["op"] == "del":
            await _release_manual_mute(bot_id, payload.group_openid, member["member_openid"])
        else:
            await group_management_service.set_member_mutes(
                bot_id,
                payload.group_openid,
                [member],
            )
    return await group_management_service.get_mute_setting(bot_id, payload.group_openid)


@router.get("/strategies")
async def list_strategies(
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.list_strategies(bot_id)


@router.post("/strategies")
async def create_strategy(
    payload: ApprovalStrategyCreate,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.create_strategy(bot_id, **payload.model_dump())


@router.patch("/strategies/{strategy_id}")
async def update_strategy(
    strategy_id: str,
    payload: ApprovalStrategyUpdate,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    body = payload.model_dump(exclude_none=True)
    group_action = body.pop("group_action", None)
    if group_action:
        mode = group_action.pop("group_mode")
        groups = group_action.pop("groups")
        body["group_action"] = {
            "op": group_action["op"],
            **group_management_service._group_body(mode, groups),
        }
    return await group_management_service.update_strategy(bot_id, strategy_id, body)


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(
    strategy_id: str,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.delete_strategy(bot_id, strategy_id)


@router.post("/strategies/{strategy_id}/execute")
async def execute_strategy(
    strategy_id: str,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.execute_strategy(bot_id, strategy_id)


@router.post("/strategies/{strategy_id}/whitelist")
async def update_whitelist(
    strategy_id: str,
    payload: ApprovalWhitelistUpdate,
    bot_id: str = Query(...),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.update_whitelist(
        bot_id,
        strategy_id,
        payload.op,
        payload.whitelist_users,
    )


@router.post("/groups/info")
async def refresh_group_info(
    bot_id: str = Query(...),
    group_openid: str = Query(..., min_length=1, max_length=128),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return await group_management_service.refresh_group_info(bot_id, group_openid)
