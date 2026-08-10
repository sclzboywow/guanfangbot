from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
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
from app.services.group_verification_service import extract_group_number, extract_group_openid
from app.services.qqbot_client import QQBotClient, client_manager


REQUIRED_EVENTS = ("GROUP_JOIN_REQUEST",)
JOIN_REQUEST_POLL_INTERVAL_SECONDS = 60
JOIN_REQUEST_POLL_GROUP_GAP_SECONDS = 2.5
logger = logging.getLogger(__name__)


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


def _is_not_group_admin(exc: Exception | dict[str, Any] | None = None, *, result: dict[str, Any] | None = None) -> bool:
    """Official QQ returns code 11703 / 'not group admin' when the bot lacks admin rights."""
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            if detail.get("qq_code") == 11703:
                return True
            data = detail.get("qq_data")
            if isinstance(data, dict) and _error_code(data) == 11703:
                return True
            message = str(detail.get("message") or "")
            if "not group admin" in message or "不是群管理员" in message or "无该群管理" in message:
                return True
        return "not group admin" in str(detail)
    payload = result if isinstance(result, dict) else None
    if payload is not None:
        data = payload.get("data") if "data" in payload else payload
        if _error_code(data) == 11703:
            return True
        text = str(data or "")
        return "not group admin" in text
    return False


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
    elif code == 11703 or _is_not_group_admin(result=result):
        message = "当前机器人不是该群管理员，已跳过此群。"
        public_status = 403
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
        self._poll_task: asyncio.Task[None] | None = None
        self.last_join_request_poll_at: str | None = None
        self.last_join_request_poll_summary: dict[str, Any] = {}

    async def start(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(
                self._join_request_poll_loop(),
                name="group-join-request-poll",
            )

    async def stop(self) -> None:
        task = self._poll_task
        self._poll_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _join_request_poll_loop(self) -> None:
        # Stagger the first sweep slightly so startup API traffic settles first.
        await asyncio.sleep(8)
        while True:
            try:
                self.last_join_request_poll_summary = await self.poll_all_join_requests()
                self.last_join_request_poll_at = datetime.now(timezone.utc).isoformat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("group join-request poll sweep failed")
            await asyncio.sleep(JOIN_REQUEST_POLL_INTERVAL_SECONDS)

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
        record_log: bool = True,
    ) -> Any:
        client = await self._client_provider(bot_id)
        result = await client.request(method, path, query, body)
        status_code = int(result.get("status_code", 500))
        success = status_code < 300
        if record_log:
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
            is_new_group = self.repository.remember_group(
                bot_id,
                group_openid,
                group_id=extract_group_number(payload),
                group_name=str(event_data.get("group_name") or ""),
                group_finger_memo=str(event_data.get("group_finger_memo") or ""),
                group_class_text=str(event_data.get("group_class_text") or ""),
                group_tags=event_data.get("group_tags") if isinstance(event_data.get("group_tags"), list) else None,
                group_member_num=event_data.get("group_member_num") if isinstance(event_data.get("group_member_num"), int) else None,
                source=f"event:{event_type}",
            )
            # Events usually omit group_name; pull /info for first sighting or unsynced empty names.
            if is_new_group or self.repository.needs_group_info(bot_id, group_openid):
                try:
                    await self.refresh_group_info(bot_id, group_openid)
                except HTTPException as exc:
                    detail = exc.detail
                    message = detail.get("message") if isinstance(detail, dict) else str(detail)
                    self.repository.remember_group(
                        bot_id,
                        group_openid,
                        group_id=extract_group_number(payload),
                        source=f"event:{event_type}",
                        info_synced=True,
                        info_sync_error=str(message or detail)[:500],
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

    async def backfill_missing_group_names(self, bot_id: str, *, limit: int = 10) -> dict[str, int]:
        """Best-effort /info refresh for groups still missing display names."""
        refreshed = 0
        failed = 0
        for group in self.repository.list_groups_missing_names(bot_id, limit=limit):
            group_openid = str(group.get("group_openid") or "")
            if not group_openid:
                continue
            try:
                await self.refresh_group_info(bot_id, group_openid)
                refreshed += 1
            except HTTPException as exc:
                failed += 1
                detail = exc.detail
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
                self.repository.remember_group(
                    bot_id,
                    group_openid,
                    source="group_info_backfill",
                    info_synced=True,
                    info_sync_error=str(message or detail)[:500],
                )
        return {"refreshed": refreshed, "failed": failed, "checked": refreshed + failed}

    async def sync_join_requests(
        self,
        bot_id: str,
        group_openid: str,
        *,
        record_logs: bool = True,
        source: str = "manual_sync",
    ) -> dict[str, Any]:
        group_openid = str(group_openid or "").strip()
        if not group_openid:
            raise HTTPException(status_code=422, detail="请先选择或填写群 OpenID")
        self.repository.remember_group(bot_id, group_openid, source=source)
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
                record_log=record_logs,
            )
            page = data if isinstance(data, dict) else {}
            items = page.get("list") if isinstance(page.get("list"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = dict(item)
                normalized["group_openid"] = group_openid
                if self.repository.upsert_join_request(bot_id, normalized, source=source):
                    synced += 1
            pages += 1
            next_cursor = str(page.get("next_cursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                cursor = ""
                break
            cursor = next_cursor
        return {"synced": synced, "pages": pages, "truncated": bool(cursor)}

    async def poll_all_join_requests(self) -> dict[str, Any]:
        """Pull official join-request lists for every remembered group.

        Official events can be missed while the process is down; this sweep
        keeps the admin queue warm without exceeding the 30 QPM list limit.
        Groups where the bot is not an admin are skipped quietly.
        """
        targets = self.repository.list_group_targets()
        groups = 0
        synced = 0
        failed = 0
        skipped_not_admin = 0
        for index, (bot_id, group_openid) in enumerate(targets):
            try:
                result = await self.sync_join_requests(
                    bot_id,
                    group_openid,
                    record_logs=False,
                    source="scheduled_poll",
                )
                groups += 1
                synced += int(result.get("synced") or 0)
            except HTTPException as exc:
                if _is_not_group_admin(exc):
                    skipped_not_admin += 1
                    logger.info(
                        "skip join-request poll: bot is not group admin bot=%s group=%s",
                        bot_id,
                        group_openid,
                    )
                else:
                    failed += 1
                    logger.warning(
                        "scheduled join-request sync failed bot=%s group=%s detail=%s",
                        bot_id,
                        group_openid,
                        exc.detail,
                    )
            except Exception:
                failed += 1
                logger.exception(
                    "scheduled join-request sync failed bot=%s group=%s",
                    bot_id,
                    group_openid,
                )
            if index + 1 < len(targets):
                await asyncio.sleep(JOIN_REQUEST_POLL_GROUP_GAP_SECONDS)
        if targets:
            # One compact breadcrumb per sweep instead of a log row for every page.
            self.repository.add_log(
                bot_id=targets[0][0],
                action="scheduled_join_request_poll",
                success=failed == 0,
                detail=(
                    f"groups={groups} synced={synced} failed={failed} "
                    f"skipped_not_admin={skipped_not_admin} targets={len(targets)}"
                ),
            )
        return {
            "targets": len(targets),
            "groups": groups,
            "synced": synced,
            "failed": failed,
            "skipped_not_admin": skipped_not_admin,
            "interval_seconds": JOIN_REQUEST_POLL_INTERVAL_SECONDS,
        }

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
        if not self.repository.get_settings(bot_id)["manual_approval_enabled"]:
            raise HTTPException(status_code=409, detail="人工审批开关已关闭")
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
        if not self.repository.get_settings(bot_id)["auto_approval_enabled"]:
            raise HTTPException(status_code=409, detail="白名单自动审批开关已关闭")
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
        if body.get("is_enable") == "on" and not self.repository.get_settings(bot_id)["auto_approval_enabled"]:
            raise HTTPException(status_code=409, detail="白名单自动审批开关已关闭")
        data = await self._request(
            bot_id,
            "PATCH",
            f"/v2/groups/join_approval_strategy/{quote(strategy_id, safe='')}",
            body=body,
            action="update_approval_strategy",
            strategy_id=strategy_id,
        )
        return data if isinstance(data, dict) else {}

    async def disable_enabled_strategies(self, bot_id: str) -> int:
        data = await self.list_strategies(bot_id)
        disabled = 0
        for strategy in data["strategies"]:
            if strategy.get("is_enable") != "on":
                continue
            strategy_id = str(strategy.get("strategy_id") or "").strip()
            if not strategy_id:
                continue
            await self.update_strategy(bot_id, strategy_id, {"is_enable": "off"})
            disabled += 1
        return disabled

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
        if not self.repository.get_settings(bot_id)["auto_approval_enabled"]:
            raise HTTPException(status_code=409, detail="白名单自动审批开关已关闭")
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
        if not self.repository.get_settings(bot_id)["auto_approval_enabled"]:
            raise HTTPException(status_code=409, detail="白名单自动审批开关已关闭")
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
            group_id=str(info.get("group_id") or ""),
            group_name=str(info.get("group_name") or ""),
            group_finger_memo=str(info.get("group_finger_memo") or ""),
            group_class_text=str(info.get("group_class_text") or ""),
            group_tags=info.get("group_tags") if isinstance(info.get("group_tags"), list) else None,
            group_member_num=info.get("group_member_num") if isinstance(info.get("group_member_num"), int) else None,
            source="group_info_api",
            info_synced=True,
        )
        return info


group_management_service = GroupManagementService()
