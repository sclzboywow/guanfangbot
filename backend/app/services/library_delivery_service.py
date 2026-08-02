from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from app.services.baidu_pan_client import BaiduPanShareClient, baidu_pan_share_client
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
from app.services.library_catalog import LibraryCatalogError, search_catalog
from app.services.library_delivery_repository import LibraryDeliveryRepository, library_delivery_repository
from app.services.qqbot_client import QQBotClient, client_manager

REQUIRED_EVENTS = ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE")
MENTION_TAG_PATTERN = re.compile(r"<@!?[^>]+>")
LEADING_MENTION_PATTERN = re.compile(r"^\s*[@＠][^\s，,：:]+[\s，,：:]*")
SELECTION_PATTERN = re.compile(r"[1-5]")


def extract_search_query(content: str) -> str:
    text = MENTION_TAG_PATTERN.sub(" ", str(content or ""))
    text = LEADING_MENTION_PATTERN.sub("", text, count=1)
    return single_line(text).strip(" ，,：:")


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
    ) -> None:
        self.repository = repository
        self.share_client = share_client
        self._qq_client_provider = qq_client_provider or client_manager.get

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
        if event_type == "GROUP_AT_MESSAGE_CREATE":
            await self._handle_search(bot_id, group_openid, member_openid, payload, settings)
        else:
            await self._handle_selection(bot_id, group_openid, member_openid, payload, settings)

    async def _send(
        self,
        bot_id: str,
        group_openid: str,
        content: str,
        *,
        msg_id: str | None = None,
    ) -> dict[str, Any]:
        client = await self._qq_client_provider(bot_id)
        return await client.send_group_text(group_openid, single_line(content), msg_id=msg_id or None)

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
            total, results = search_catalog(settings, query, limit=5)
        except LibraryCatalogError as exc:
            self.repository.add_log(
                bot_id=bot_id, action="search", success=False,
                group_openid=group_openid, member_openid=member_openid,
                query=query, detail=str(exc),
            )
            await self._send(bot_id, group_openid, "资料库暂不可用，请联系管理员检查数据库配置。", msg_id=message_id)
            return
        if total <= 0 or not results:
            self.repository.add_log(
                bot_id=bot_id, action="search", success=True,
                group_openid=group_openid, member_openid=member_openid,
                query=query, detail="0 results",
            )
            await self._send(bot_id, group_openid, f"没有找到标题包含“{_short_title(query)}”的资料。", msg_id=message_id)
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
        choices = "；".join(f"{index}.{_short_title(item['title'])}" for index, item in enumerate(results, 1))
        ttl_minutes = max(1, int(settings["session_ttl_seconds"]) // 60)
        message = f"找到{total}个结果，前{len(results)}个：{choices} 请在{ttl_minutes}分钟内直接回复编号1-{len(results)}。"
        result = await self._send(bot_id, group_openid, message, msg_id=message_id)
        status_code = int(result.get("status_code", 0)) or None
        self.repository.add_log(
            bot_id=bot_id, session_id=str(session["id"]), action="search",
            success=status_code is not None and 200 <= status_code < 300,
            status_code=status_code, group_openid=group_openid,
            member_openid=member_openid, query=query,
            detail=str(result.get("data", "")),
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
        token = str(settings.get("access_token") or "").strip()
        if not token:
            self.repository.add_log(
                bot_id=bot_id, session_id=str(session["id"]), action="share_created",
                success=False, group_openid=group_openid, member_openid=member_openid,
                query=str(session["query"]), title=str(item.get("title") or ""),
                fsid=str(item.get("fsid") or ""), detail="百度网盘 Access Token 未配置",
            )
            await self._send(bot_id, group_openid, "创建分享失败，请联系管理员配置百度网盘授权。", msg_id=message_id)
            return
        share = await self.share_client.create_share(
            api_url=str(settings["api_url"]),
            api_method=str(settings["api_method"]),
            access_token=token,
            fsids=[str(item.get("fsid") or "")],
            period=int(settings["share_period"]),
        )
        if not share.get("success"):
            self.repository.add_log(
                bot_id=bot_id, session_id=str(session["id"]), action="share_created",
                success=False, status_code=share.get("status_code"),
                group_openid=group_openid, member_openid=member_openid,
                query=str(session["query"]), title=str(item.get("title") or ""),
                fsid=str(item.get("fsid") or ""), detail=str(share.get("detail") or ""),
            )
            await self._send(bot_id, group_openid, "创建分享失败，请稍后重试或联系管理员。", msg_id=message_id)
            return
        if not self.repository.consume_session(str(session["id"])):
            return
        title = _short_title(str(item.get("title") or ""), limit=80)
        message = (
            f"标题：{title} 分享链接：{share['link']} "
            f"提取码：{share['pwd']} 有效期：{period_text(int(share.get('period', settings['share_period'])))}"
        )
        send_result = await self._send(bot_id, group_openid, message, msg_id=message_id)
        send_code = int(send_result.get("status_code", 0)) or None
        send_success = send_code is not None and 200 <= send_code < 300
        self.repository.add_log(
            bot_id=bot_id, session_id=str(session["id"]), action="share_created",
            success=send_success, status_code=send_code,
            group_openid=group_openid, member_openid=member_openid,
            query=str(session["query"]), title=str(item.get("title") or ""),
            fsid=str(item.get("fsid") or ""), detail=str(send_result.get("data", "")),
        )


library_delivery_service = LibraryDeliveryService()
