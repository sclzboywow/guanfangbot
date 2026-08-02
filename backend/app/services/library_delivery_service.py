from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from app.services.baidu_oauth_service import BaiduOAuthError, BaiduOAuthService, baidu_oauth_service
from app.services.baidu_pan_client import BaiduPanShareClient, baidu_pan_share_client
from app.services.bot_repository import BotRepository, bot_repository
from app.services.group_moderation_repository import group_moderation_repository
from app.services.group_moderation_service import active_block, utc_now_dt
from app.services.group_verification_repository import group_verification_repository
from app.services.group_verification_service import (
    extract_group_openid,
    extract_member_openid,
    extract_message_content,
    extract_message_id,
    is_bot_author,
    single_line,
)
from app.services.library_catalog import LibraryCatalogError, is_hash_pan_path, search_catalog
from app.services.library_delivery_repository import LibraryDeliveryRepository, library_delivery_repository
from app.services.qqbot_client import QQBotClient, client_manager

REQUIRED_EVENTS = ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE")
MENTION_TAG_PATTERN = re.compile(r"<@!?[^>]+>")
LEADING_MENTION_PATTERN = re.compile(r"^\s*[@＠][^\s，,：:]+[\s，,：:]*")
SELECTION_PATTERN = re.compile(r"[1-5]")
SEARCH_CANDIDATE_LIMIT = 40
SEARCH_RESULT_LIMIT = 5


def extract_search_query(content: str) -> str:
    text = MENTION_TAG_PATTERN.sub(" ", str(content or ""))
    text = LEADING_MENTION_PATTERN.sub("", text, count=1)
    return single_line(text).strip(" ，,：:")


def is_bot_mentioned(payload: dict[str, Any]) -> bool:
    """True when the message @mentions this bot (full-group message mode uses GROUP_MESSAGE_CREATE)."""
    data = payload.get("d") if isinstance(payload.get("d"), dict) else payload
    if not isinstance(data, dict):
        return False
    mentions = data.get("mentions") or []
    if not isinstance(mentions, list):
        return False
    for item in mentions:
        if not isinstance(item, dict):
            continue
        # QQ 全量群消息里，@本机器人通常带 is_you=true；兼容仅标记 bot=true 的情况。
        if item.get("is_you") is True or item.get("bot") is True:
            return True
    return False


def period_text(period: int) -> str:
    return "永久" if int(period) == 0 else f"{int(period)}天"


def _short_title(value: str, limit: int = 42) -> str:
    title = single_line(value).replace("；", " ").strip()
    return title if len(title) <= limit else f"{title[:limit - 1]}…"


class LibraryDeliveryService:
    def __init__(
        self,
        repository: LibraryDeliveryRepository = library_delivery_repository,
        share_client: BaiduPanShareClient = baidu_pan_share_client,
        qq_client_provider: Callable[[str], Awaitable[QQBotClient]] | None = None,
        oauth_service: BaiduOAuthService = baidu_oauth_service,
        bots: BotRepository = bot_repository,
    ) -> None:
        self.repository = repository
        self.share_client = share_client
        self.oauth_service = oauth_service
        self.bots = bots
        self._qq_client_provider = qq_client_provider or client_manager.get

    def _owner_user_id(self, bot_id: str) -> str | None:
        return self.bots.get_owner_user_id(bot_id)

    async def handle_event(self, bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
        if event_type not in REQUIRED_EVENTS or is_bot_author(payload):
            return
        settings = self.repository.get_private_settings(bot_id)
        if not settings["enabled"]:
            return
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        if not group_openid or not member_openid:
            return
        if group_verification_repository.get_pending_session(bot_id, group_openid, member_openid) is not None:
            return
        moderation_member = group_moderation_repository.get_member(bot_id, group_openid, member_openid)
        if active_block(moderation_member, utc_now_dt()):
            return
        # 开通群全量消息后，@机器人常见为 GROUP_MESSAGE_CREATE + mentions，而不一定是 GROUP_AT_MESSAGE_CREATE。
        if event_type == "GROUP_AT_MESSAGE_CREATE" or is_bot_mentioned(payload):
            await self._handle_search(bot_id, group_openid, member_openid, payload, settings)
            return
        if event_type == "GROUP_MESSAGE_CREATE":
            await self._handle_selection(bot_id, group_openid, member_openid, payload, settings)

    async def _send(
        self,
        bot_id: str,
        group_openid: str,
        content: str,
        *,
        msg_id: str | None = None,
        multiline: bool = False,
    ) -> dict[str, Any]:
        client = await self._qq_client_provider(bot_id)
        text = content if multiline else single_line(content)
        return await client.send_group_text(
            group_openid,
            text,
            msg_id=msg_id or None,
            collapse_whitespace=not multiline,
        )

    async def _pick_shareable_results(
        self,
        bot_id: str,
        candidates: list[dict[str, str]],
        *,
        need: int = SEARCH_RESULT_LIMIT,
    ) -> list[dict[str, str]]:
        """Keep only files that still exist on the authorized Netdisk, refreshing stale fsids."""
        if not candidates or need <= 0:
            return []
        owner_user_id = self._owner_user_id(bot_id)
        try:
            if not owner_user_id:
                raise BaiduOAuthError("机器人尚未归属用户，无法读取网盘授权")
            token = await self.oauth_service.get_access_token(owner_user_id)
        except BaiduOAuthError:
            # Authorization missing: still return hash-path candidates for later share error handling.
            return [
                dict(item)
                for item in candidates
                if is_hash_pan_path(str(item.get("pan_path") or ""))
            ][:need]

        selected: list[dict[str, str]] = []
        for item in candidates:
            if len(selected) >= need:
                break
            path = str(item.get("pan_path") or "").strip()
            fsid = str(item.get("fsid") or "").strip()
            live = await self.share_client.resolve_fsid_by_path(access_token=token, pan_path=path)
            if live:
                selected.append({**item, "fsid": live})
                continue
            if fsid and await self.share_client.fsid_exists(access_token=token, fsid=fsid):
                selected.append(dict(item))
        return selected

    async def _handle_search(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        payload: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        message_id = extract_message_id(payload)
        if not self.repository.claim_message(bot_id, message_id, "search"):
            return
        query = extract_search_query(extract_message_content(payload))
        if not query:
            await self._send(bot_id, group_openid, "请在@机器人后输入要查找的资料标题。", msg_id=message_id)
            return
        if len(query) > 100:
            await self._send(bot_id, group_openid, "检索内容过长，请缩短到100个字符以内。", msg_id=message_id)
            return
        try:
            total, candidates = search_catalog(settings, query, limit=SEARCH_CANDIDATE_LIMIT)
        except LibraryCatalogError as exc:
            self.repository.add_log(
                bot_id=bot_id, action="search", success=False,
                group_openid=group_openid, member_openid=member_openid,
                query=query, detail=str(exc),
            )
            await self._send(bot_id, group_openid, "资料库暂不可用，请联系管理员检查数据库配置。", msg_id=message_id)
            return
        if total <= 0 or not candidates:
            self.repository.add_log(
                bot_id=bot_id, action="search", success=True,
                group_openid=group_openid, member_openid=member_openid,
                query=query, detail="0 results",
            )
            await self._send(bot_id, group_openid, f"没有找到标题包含“{_short_title(query)}”的资料。", msg_id=message_id)
            return
        results = await self._pick_shareable_results(bot_id, candidates, need=SEARCH_RESULT_LIMIT)
        if not results:
            self.repository.add_log(
                bot_id=bot_id, action="search", success=False,
                group_openid=group_openid, member_openid=member_openid,
                query=query, detail=f"catalog_hits={total} shareable=0",
            )
            await self._send(
                bot_id,
                group_openid,
                f"找到{total}个相关标题，但当前网盘中暂无可分享文件，请换个关键词或联系管理员更新索引。",
                msg_id=message_id,
            )
            return
        session = self.repository.create_session(
            bot_id=bot_id,
            group_openid=group_openid,
            member_openid=member_openid,
            query=query,
            total_count=total,
            results=results,
            ttl_seconds=int(settings["session_ttl_seconds"]),
        )
        ttl_minutes = max(1, int(settings["session_ttl_seconds"]) // 60)
        choices = "\n".join(
            f"{index}. {_short_title(item['title'])}" for index, item in enumerate(results, 1)
        )
        message = (
            f"找到{total}个结果，前{len(results)}个：\n"
            f"{choices}\n"
            f"请在{ttl_minutes}分钟内直接回复编号1-{len(results)}。"
        )
        result = await self._send(bot_id, group_openid, message, msg_id=message_id, multiline=True)
        status_code = int(result.get("status_code", 0)) or None
        self.repository.add_log(
            bot_id=bot_id, session_id=str(session["id"]), action="search",
            success=status_code is not None and 200 <= status_code < 300,
            status_code=status_code, group_openid=group_openid,
            member_openid=member_openid, query=query,
            detail=str(result.get("data", "")),
        )

    async def _create_share_with_refresh(
        self,
        bot_id: str,
        settings: dict[str, Any],
        fsid: str,
        pan_path: str = "",
    ) -> dict[str, Any]:
        owner_user_id = self._owner_user_id(bot_id)
        if not owner_user_id:
            raise BaiduOAuthError("机器人尚未归属用户，无法读取网盘授权")
        token = await self.oauth_service.get_access_token(owner_user_id)
        share = await self.share_client.create_share(
            api_url=str(settings["api_url"]),
            api_method=str(settings["api_method"]),
            access_token=token,
            fsids=[fsid],
            period=int(settings["share_period"]),
            pan_path=pan_path or None,
        )
        if share.get("success") or not share.get("auth_error"):
            return share
        refreshed = await self.oauth_service.get_access_token(owner_user_id, force_refresh=True)
        return await self.share_client.create_share(
            api_url=str(settings["api_url"]),
            api_method=str(settings["api_method"]),
            access_token=refreshed,
            fsids=[fsid],
            period=int(settings["share_period"]),
            pan_path=pan_path or None,
        )

    async def _handle_selection(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        payload: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        content = single_line(extract_message_content(payload)).strip()
        if not SELECTION_PATTERN.fullmatch(content):
            return
        session = self.repository.get_active_session(bot_id, group_openid, member_openid)
        if session is None:
            return
        message_id = extract_message_id(payload)
        if not self.repository.claim_message(bot_id, message_id, "selection"):
            return
        selection = int(content) - 1
        results = session.get("results") or []
        if selection < 0 or selection >= len(results):
            await self._send(bot_id, group_openid, f"编号无效，请回复1-{len(results)}。", msg_id=message_id)
            return
        item = results[selection]
        fsid = str(item.get("fsid") or "")
        pan_path = str(item.get("pan_path") or "")
        try:
            share = await self._create_share_with_refresh(bot_id, settings, fsid, pan_path)
        except BaiduOAuthError as exc:
            self.repository.add_log(
                bot_id=bot_id, session_id=str(session["id"]), action="share_created",
                success=False, group_openid=group_openid, member_openid=member_openid,
                query=str(session["query"]), title=str(item.get("title") or ""),
                fsid=fsid, detail=str(exc),
            )
            await self._send(bot_id, group_openid, "创建分享失败，请联系管理员完成百度网盘扫码授权。", msg_id=message_id)
            return
        if not share.get("success"):
            detail = str(share.get("detail") or "")
            self.repository.add_log(
                bot_id=bot_id, session_id=str(session["id"]), action="share_created",
                success=False, status_code=share.get("status_code"),
                group_openid=group_openid, member_openid=member_openid,
                query=str(session["query"]), title=str(item.get("title") or ""),
                fsid=str(share.get("fsid") or fsid), detail=detail,
            )
            if "删除" in detail or "移动" in detail:
                hint = "该文件在网盘中不存在或索引已过期，请换一个编号"
            elif detail and len(detail) <= 40:
                hint = detail.rstrip("。")
            else:
                hint = "请稍后重试或联系管理员"
            await self._send(bot_id, group_openid, f"创建分享失败，{hint}。", msg_id=message_id)
            return
        if not self.repository.consume_session(str(session["id"])):
            return
        title = _short_title(str(item.get("title") or ""), limit=80)
        message = (
            f"标题：{title}\n"
            f"分享链接：{share['link']}\n"
            f"提取码：{share['pwd']}\n"
            f"有效期：{period_text(int(share.get('period', settings['share_period'])))}"
        )
        send_result = await self._send(bot_id, group_openid, message, msg_id=message_id, multiline=True)
        send_code = int(send_result.get("status_code", 0)) or None
        send_success = send_code is not None and 200 <= send_code < 300
        self.repository.add_log(
            bot_id=bot_id, session_id=str(session["id"]), action="share_created",
            success=send_success, status_code=send_code,
            group_openid=group_openid, member_openid=member_openid,
            query=str(session["query"]), title=str(item.get("title") or ""),
            fsid=fsid, detail=str(send_result.get("data", "")),
        )


library_delivery_service = LibraryDeliveryService()
