from __future__ import annotations

from typing import Any, Awaitable, Callable
from urllib.parse import quote

from fastapi import HTTPException

from app.services.group_management_repository import (
    GroupManagementRepository,
    group_management_repository,
)
from app.services.group_mute_repository import (
    GroupMuteLeaseRepository,
    group_mute_lease_repository,
    parse_time,
)
from app.services.group_verification_service import extract_group_openid
from app.services.qqbot_client import QQBotClient, client_manager


REQUIRED_EVENTS = ("GROUP_JOIN_REQUEST",)


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("d")
    return value if isinstance(value, dict) else payload


def _error_code(data: Any) -> int | None:
    if not isinstance(data, dict):
        return None
    for key in ("code", "error_code", "errcode"):
        value = data.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _friendly_error(action: str, result: dict[str, Any]) -> HTTPException:
    status_code = int(result.get("status_code", 500))
    data = result.get("data")
    code = _error_code(data)
    if code == 11004:
        message = "这条入群申请已经失效或被处理，请刷新申请列表后重试。"
        public_status = 409
    elif code == 12905:
        message = "该自动审批策略尚未启用，请先启用策略再执行扫描。"
        public_status = 409
    elif code == 11253:
        message = "当前机器人没有该接口权限；群名称可能无法读取，但不影响使用群 OpenID 管理。"
        public_status = 403
    elif status_code == 429:
        message = "QQ 官方接口调用过于频繁，请稍后再试。"
        public_status = 429
    elif status_code in {401, 403}:
        message = "QQ 拒绝了本次操作，请确认机器人已被设为该群管理员并已开通对应能力。"
        public_status = 403
    else:
        message = f"{action}失败，QQ 返回：{data}"
        public_status = 502
    return HTTPException(
        status_code=public_status,
        detail={"message": message, "qq_status": status_code, "qq_code": code, "qq_data": data},
    )


class GroupManagementService:
    def __init__(
        self,
        repository: GroupManagementRepository = group_management_repository,
        client_provider: Callable[[str], Awaitable[QQBotClient]] | None = None,
    ) -> None:
        self.repository = repository
        self._client_provider = client_provider or client_manager.get
        self._mute_repository = (
            group_mute_lease_repository
            if repository is group_management_repository and client_provider is None
            else GroupMuteLeaseRepository(repository.path.with_name("group_mute_leases.db"))
        )

    async def _request(
        self,
        bot_id: str,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: Any | None = None,
        action: str,
        group_openid: str = "",
        member_openid: str = "",
        strategy_id: str = "",
    ) -> Any:
        client = await self._client_provider(bot_id)
        result = await client.request(method, path, query, body)
        status_code = int(result.get("status_code", 500))
        success = status_code < 300
        self.repository.add_log(
            bot_id=bot_id,
            action=action,
            success=success,
            group_openid=group_openid,
            member_openid=member_openid,
            strategy_id=strategy_id,
            status_code=status_code,
            detail=str(result.get("data", "")),
        )
        if not success:
            raise _friendly_error(action, result)
        return result.get("data")

    async def handle_event(self, bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
        group_openid = extract_group_openid(payload)
        if group_openid:
            event_data = _data(payload)
            self.repository.remember_group(
                bot_id,
                group_openid,
                group_name=str(event_data.get("group_name") or ""),
                source=f"event:{event_type}",
            )
        if event_type != "GROUP_JOIN_REQUEST":
            return
        event_data = dict(_data(payload))
        if group_openid and not event_data.get("group_openid"):
            event_data["group_openid"] = group_openid
        recorded = self.repository.upsert_join_request(bot_id, event_data, source="event")
        self.repository.add_log(
            bot_id=bot_id,
            action="join_request_event",
            success=recorded is not None,
            group_openid=group_openid,
            member_openid=str(event_data.get("member_openid") or ""),
            strategy_id=str((event_data.get("auto_approved") or {}).get("strategy_id") or "")
            if isinstance(event_data.get("auto_approved"), dict)
            else "",
            detail="已接收入群申请事件" if recorded else "事件缺少必要标识",
        )

    async def sync_join_requests(self, bot_id: str, group_openid: str) -> dict[str, Any]:
        group_openid = str(group_openid or "").strip()
        if not group_openid:
            raise HTTPException(status_code=422, detail="请先选择或填写群 OpenID")
        self.repository.remember_group(bot_id, group_openid, source="manual_sync")
        cursor = ""
        synced = 0
        pages = 0
        while pages < 10:
            data = await self._request(
                bot_id,
                "GET",
                f"/v2/groups/{quote(group_openid, safe='')}/join_request_list",
                query={"limit": "100", **({"cursor": cursor} if cursor else {})},
                action="sync_join_requests",
                group_openid=group_openid,
            )
            page = data if isinstance(data, dict) else {}
            items = page.get("list") if isinstance(page.get("list"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = dict(item)
                normalized["group_openid"] = group_openid
                if self.repository.upsert_join_request(bot_id, normalized, source="api_sync"):
                    synced += 1
            pages += 1
            next_cursor = str(page.get("next_cursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                cursor = ""
                break
            cursor = next_cursor
        return {"synced": synced, "pages": pages, "truncated": bool(cursor)}

    async def decide_join_request(
        self,
        bot_id: str,
        *,
        group_openid: str,
        member_openid: str,
        join_request_id: str,
        op: str,
        reject_reason: str = "",
        add_to_member_blacklist: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"op": op, "join_request_id": join_request_id}
        if op == "decline":
            if reject_reason:
                body["reject_reason"] = reject_reason
            body["add_to_member_blacklist"] = bool(add_to_member_blacklist)
        await self._request(
            bot_id,
            "POST",
            (
                f"/v2/groups/{quote(group_openid, safe='')}/approval_join_request/"
                f"{quote(member_openid, safe='')}"
            ),
            body=body,
            action=f"join_request_{op}",
            group_openid=group_openid,
            member_openid=member_openid,
        )
        self.repository.mark_decision(
            bot_id,
            join_request_id,
            decision=op,
            detail=reject_reason,
        )
        return {"ok": True, "decision": op}

    async def get_mute_setting(self, bot_id: str, group_openid: str) -> dict[str, Any]:
        group_openid = str(group_openid or "").strip()
        self.repository.remember_group(bot_id, group_openid, source="mute_query")
        data = await self._request(
            bot_id,
            "GET",
            f"/v2/groups/{quote(group_openid, safe='')}/restrict_chat_setting",
            action="get_mute_setting",
            group_openid=group_openid,
        )
        return data if isinstance(data, dict) else {"global_rule": {}, "members": []}

    async def set_member_mutes(
        self,
        bot_id: str,
        group_openid: str,
        members: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not 1 <= len(members) <= 10:
            raise HTTPException(status_code=422, detail="每次请选择 1 至 10 名成员")
        normalized: list[dict[str, Any]] = []
        for member in members:
            item = dict(member)
            member_openid = str(item.get("member_openid") or "")
            if item.get("op") == "del":
                normalized.append(item)
                continue
            requested = parse_time(str(item.get("mute_expire_at") or ""))
            leases = self._mute_repository.active_leases(
                bot_id, group_openid, member_openid
            )
            other_sources = [lease for lease in leases if lease["source"] != "manual"]
            if requested is not None and leases:
                effective = max([requested, *[lease["expire_at_dt"] for lease in other_sources]])
                item["mute_expire_at"] = effective.isoformat()
                item["op"] = "update"
            normalized.append(item)
        await self._request(
            bot_id,
            "POST",
            f"/v2/groups/{quote(group_openid, safe='')}/restrict_chat_setting",
            body={"members": normalized},
            action="set_member_mutes",
            group_openid=group_openid,
        )
        for original in members:
            member_openid = str(original.get("member_openid") or "")
            if original.get("op") == "del":
                self._mute_repository.clear_member(bot_id, group_openid, member_openid)
            else:
                self._mute_repository.upsert(
                    bot_id,
                    group_openid,
                    member_openid,
                    "manual",
                    str(original.get("mute_expire_at") or ""),
                    detail="官方群管理手动设置",
                )
        return await self.get_mute_setting(bot_id, group_openid)

    async def list_strategies(self, bot_id: str) -> dict[str, Any]:
        cursor = ""
        strategies: list[dict[str, Any]] = []
        pages = 0
        while pages < 5:
            data = await self._request(
                bot_id,
                "GET",
                "/v2/groups/join_approval_strategy",
                query={"limit": "100", **({"cursor": cursor} if cursor else {})},
                action="list_approval_strategies",
            )
            page = data if isinstance(data, dict) else {}
            strategies.extend(item for item in page.get("strategies", []) if isinstance(item, dict))
            pages += 1
            next_cursor = str(page.get("next_cursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                cursor = ""
                break
            cursor = next_cursor
        return {"strategies": strategies, "truncated": bool(cursor)}

    @staticmethod
    def _group_body(mode: str, groups: list[str]) -> dict[str, Any]:
        if mode == "group_ids":
            return {"group_ids": [int(item) for item in groups]}
        return {"group_openids": groups}

    async def create_strategy(
        self,
        bot_id: str,
        *,
        group_mode: str,
        groups: list[str],
        is_enable: str,
        expire_at: str | None,
        remark: str,
    ) -> dict[str, Any]:
        body = {
            **self._group_body(group_mode, groups),
            "is_enable": is_enable,
            **({"expire_at": expire_at} if expire_at else {}),
            **({"remark": remark} if remark else {}),
        }
        data = await self._request(
            bot_id,
            "POST",
            "/v2/groups/join_approval_strategy",
            body=body,
            action="create_approval_strategy",
        )
        return data if isinstance(data, dict) else {}

    async def update_strategy(self, bot_id: str, strategy_id: str, body: dict[str, Any]) -> dict[str, Any]:
        data = await self._request(
            bot_id,
            "PATCH",
            f"/v2/groups/join_approval_strategy/{quote(strategy_id, safe='')}",
            body=body,
            action="update_approval_strategy",
            strategy_id=strategy_id,
        )
        return data if isinstance(data, dict) else {}

    async def delete_strategy(self, bot_id: str, strategy_id: str) -> dict[str, Any]:
        await self._request(
            bot_id,
            "DELETE",
            f"/v2/groups/join_approval_strategy/{quote(strategy_id, safe='')}",
            action="delete_approval_strategy",
            strategy_id=strategy_id,
        )
        return {"ok": True}

    async def execute_strategy(self, bot_id: str, strategy_id: str) -> dict[str, Any]:
        await self._request(
            bot_id,
            "POST",
            f"/v2/groups/join_approval_strategy/{quote(strategy_id, safe='')}/execute",
            body={},
            action="execute_approval_strategy",
            strategy_id=strategy_id,
        )
        return {
            "ok": True,
            "message": "扫描任务已提交，QQ 官方通常会在约 10 分钟内完成处理。",
        }

    async def update_whitelist(
        self,
        bot_id: str,
        strategy_id: str,
        op: str,
        users: list[str],
    ) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for start in range(0, len(users), 10000):
            batch = users[start : start + 10000]
            data = await self._request(
                bot_id,
                "POST",
                f"/v2/groups/join_approval_strategy/{quote(strategy_id, safe='')}/whitelist_users",
                body={"op": op, "whitelist_users": batch},
                action=f"whitelist_{op}",
                strategy_id=strategy_id,
            )
            if isinstance(data, dict):
                last = data
        return {**last, "processed": len(users)}

    async def refresh_group_info(self, bot_id: str, group_openid: str) -> dict[str, Any]:
        data = await self._request(
            bot_id,
            "GET",
            f"/v2/groups/{quote(group_openid, safe='')}/info",
            action="get_group_info",
            group_openid=group_openid,
        )
        info = data if isinstance(data, dict) else {}
        self.repository.remember_group(
            bot_id,
            group_openid,
            group_name=str(info.get("group_name") or ""),
            source="group_info_api",
        )
        return info


group_management_service = GroupManagementService()
