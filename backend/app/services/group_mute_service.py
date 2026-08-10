from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from app.services.group_mute_repository import (
    GroupMuteLeaseRepository,
    group_mute_lease_repository,
    parse_time,
)
from app.services.qqbot_client import QQBotClient, client_manager


class GroupMuteCoordinator:
    def __init__(
        self,
        repository: GroupMuteLeaseRepository = group_mute_lease_repository,
        client_provider: Callable[[str], Awaitable[QQBotClient]] | None = None,
    ) -> None:
        self.repository = repository
        self._client_provider = client_provider or client_manager.get

    async def _set(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        *,
        op: str,
        expire_at: str = "",
    ) -> dict[str, Any]:
        client = await self._client_provider(bot_id)
        member: dict[str, Any] = {"op": op, "member_openid": member_openid}
        if op != "del":
            member["mute_expire_at"] = expire_at
        return await client.request(
            "POST",
            f"/v2/groups/{quote(group_openid, safe='')}/restrict_chat_setting",
            None,
            {"members": [member]},
        )

    async def apply(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        *,
        source: str,
        expire_at: str,
        detail: str = "",
    ) -> dict[str, Any]:
        requested = parse_time(expire_at)
        if requested is None or requested <= datetime.now(timezone.utc):
            return {"status_code": 422, "data": {"message": "禁言结束时间必须晚于当前时间"}}
        existing = self.repository.active_leases(bot_id, group_openid, member_openid)
        other_sources = [item for item in existing if item["source"] != source]
        effective = max([requested, *[item["expire_at_dt"] for item in other_sources]])
        result = await self._set(
            bot_id,
            group_openid,
            member_openid,
            op="update" if existing else "add",
            expire_at=effective.isoformat(),
        )
        status_code = int(result.get("status_code", 0))
        if 200 <= status_code < 300:
            self.repository.upsert(
                bot_id, group_openid, member_openid, source, requested.isoformat(), detail=detail
            )
        return {**result, "effective_expire_at": effective.isoformat()}

    async def release(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        *,
        source: str,
    ) -> dict[str, Any]:
        all_active = self.repository.active_leases(bot_id, group_openid, member_openid)
        source_active = any(item["source"] == source for item in all_active)
        remaining = [item for item in all_active if item["source"] != source]
        if not source_active:
            effective = max((item["expire_at_dt"] for item in remaining), default=None)
            return {
                "status_code": 200,
                "data": {"message": "该来源没有有效禁言，无需解除"},
                "released_source": source,
                "still_muted": bool(remaining),
                "effective_expire_at": effective.isoformat() if effective else "",
            }
        if remaining:
            effective = max(item["expire_at_dt"] for item in remaining)
            result = await self._set(
                bot_id, group_openid, member_openid, op="update", expire_at=effective.isoformat()
            )
        else:
            effective = None
            result = await self._set(bot_id, group_openid, member_openid, op="del")
        status_code = int(result.get("status_code", 0))
        if 200 <= status_code < 300:
            self.repository.deactivate(bot_id, group_openid, member_openid, source)
        return {
            **result,
            "released_source": source,
            "still_muted": bool(remaining),
            "effective_expire_at": effective.isoformat() if effective else "",
        }

    def clear_all_sources(self, bot_id: str, group_openid: str, member_openid: str) -> None:
        self.repository.clear_member(bot_id, group_openid, member_openid)


group_mute_coordinator = GroupMuteCoordinator()
