from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

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
from app.services.group_verification_repository import group_verification_repository


router = APIRouter(prefix="/group-management", tags=["group-management"])


def _status(bot_id: str, user: AuthUser) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    configured = set(bot.event_scopes)
    known_members = {
        (item["group_openid"], item["member_openid"]): item
        for item in group_management_repository.known_members(bot_id)
    }
    for session in group_verification_repository.list_sessions(bot_id, limit=1000):
        key = (str(session["group_openid"]), str(session["member_openid"]))
        known_members[key] = {
            "group_openid": key[0],
            "member_openid": key[1],
            "username": str(session.get("member_name") or known_members.get(key, {}).get("username") or ""),
            "last_seen_at": str(session.get("last_message_at") or session.get("joined_at") or ""),
        }
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
        "known_members": list(known_members.values()),
        "join_requests": group_management_repository.list_join_requests(bot_id),
        "logs": group_management_repository.list_logs(bot_id, limit=100),
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


@router.get("/status")
def status(bot_id: str = Query(...), user: AuthUser = Depends(require_user)) -> dict[str, Any]:
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
    return await group_management_service.set_member_mutes(
        bot_id,
        payload.group_openid,
        [item.model_dump() for item in payload.members],
    )


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
