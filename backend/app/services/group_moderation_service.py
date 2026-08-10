from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.services.group_moderation_repository import GroupModerationRepository, group_moderation_repository
from app.services.group_mute_repository import GroupMuteLeaseRepository
from app.services.group_mute_service import GroupMuteCoordinator, group_mute_coordinator
from app.services.group_verification_repository import group_verification_repository
from app.services.group_verification_service import (
    extract_group_openid,
    extract_member_name,
    extract_member_openid,
    extract_message_content,
    extract_message_id,
    is_bot_author,
    single_line,
)
from app.services.qqbot_client import QQBotClient, client_manager

REQUIRED_EVENTS = ("GROUP_MESSAGE_CREATE",)
MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
LANDLINE_PATTERN = re.compile(r"(?<!\d)(?:0\d{2,3}[-\s]?\d{7,8}|(?:400|800)[-\s]?\d{3}[-\s]?\d{4})(?!\d)")
WECHAT_PATTERN = re.compile(
    r"(?:加\s*(?:微信|微\s*信|[vV]|[wW][xX])(?:[：:\s_-]*[a-zA-Z][-_a-zA-Z0-9]{5,19})?|"
    r"(?:微信|微\s*信|[vV][xX]|[wW][xX]|[wW]e[cC]hat)(?:号|联系|添加|同号)?[：:\s_-]+"
    r"(?:[a-zA-Z][-_a-zA-Z0-9]{5,19}|1[3-9]\d{9}))",
    re.IGNORECASE,
)
ADMIN_ROLES = {"admin", "owner", "群主", "管理员", "2", "4"}
MERGED_MESSAGE_TYPE = 102
MERGED_MESSAGE_PREFIX = "[群聊的聊天记录]"
CARD_MESSAGE_TYPE = 3
GROUP_CARD_TAG = "群名片"


def extract_message_type(payload: dict[str, Any]) -> int | None:
    data = payload.get("d") if isinstance(payload.get("d"), dict) else payload
    if not isinstance(data, dict):
        return None
    raw = data.get("message_type")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def extract_ark_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("d") if isinstance(payload.get("d"), dict) else payload
    if not isinstance(data, dict):
        return {}
    ark = data.get("ark_data")
    return ark if isinstance(ark, dict) else {}


def is_merged_message(payload: dict[str, Any]) -> bool:
    if extract_message_type(payload) == MERGED_MESSAGE_TYPE:
        return True
    content = extract_message_content(payload).lstrip()
    return content.startswith(MERGED_MESSAGE_PREFIX)


def is_group_card(payload: dict[str, Any]) -> bool:
    """群名片：结构化 contact_card 且 tag/jumpUrl 指向群，或 content 展平文本含群名片标记。"""
    ark = extract_ark_data(payload)
    fields = ark.get("fields") if isinstance(ark.get("fields"), dict) else {}
    tag = str(fields.get("tag") or "").strip()
    jump_url = str(fields.get("jumpUrl") or fields.get("jump_url") or "")
    prompt = str(ark.get("prompt") or "")
    if tag == GROUP_CARD_TAG or "card_type=group" in jump_url or prompt.startswith(f"{GROUP_CARD_TAG}:"):
        return True

    content = extract_message_content(payload)
    if not content:
        return False
    lowered = content.replace(" ", "")
    return (
        "tag:群名片" in lowered
        or "摘要:群名片" in lowered
        or "群名片:" in content
        or "card_type=group" in content
    )


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_member_role(payload: dict[str, Any]) -> str:
    data = payload.get("d") if isinstance(payload.get("d"), dict) else payload
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    member = data.get("member") if isinstance(data.get("member"), dict) else {}
    for value in (
        author.get("member_role"), author.get("role"), data.get("member_role"),
        member.get("role"), member.get("member_role"),
    ):
        text = str(value or "").strip().lower()
        if text:
            return text
    return ""


@dataclass(frozen=True)
class Detection:
    rule: str
    matched: str
    source: str


def detect_advertising(content: str, member_name: str, settings: dict[str, Any]) -> Detection | None:
    text = str(content or "")
    compact = re.sub(r"[\s\-—_()（）]+", "", text)
    if settings.get("detect_mobile", True):
        match = MOBILE_PATTERN.search(compact)
        if match:
            return Detection("mobile_phone", match.group(0), "content")
    if settings.get("detect_landline", True):
        match = LANDLINE_PATTERN.search(text)
        if match:
            return Detection("landline_phone", match.group(0), "content")
    if settings.get("detect_wechat", True):
        match = WECHAT_PATTERN.search(text)
        if match:
            return Detection("wechat", match.group(0), "content")
    if settings.get("detect_content_keywords", True):
        lowered = text.casefold()
        for keyword in settings.get("content_keywords", []):
            word = str(keyword).strip()
            if word and word.casefold() in lowered:
                return Detection("content_keyword", word, "content")
    if settings.get("detect_nickname_keywords", True):
        lowered_name = str(member_name or "").casefold()
        for keyword in settings.get("nickname_keywords", []):
            word = str(keyword).strip()
            if word and word.casefold() in lowered_name:
                return Detection("nickname_keyword", word, "nickname")
    return None


def active_block(member: dict[str, Any] | None, now: datetime) -> bool:
    if not member or member.get("trusted"):
        return False
    if member.get("permanent"):
        return True
    until = parse_time(member.get("blocked_until"))
    return bool(until and until > now)


def duration_text(minutes: int | None, permanent: bool) -> str:
    if permanent:
        return "永久"
    value = int(minutes or 0)
    if value % 1440 == 0 and value >= 1440:
        return f"{value // 1440}天"
    if value % 60 == 0 and value >= 60:
        return f"{value // 60}小时"
    return f"{value}分钟"


class GroupModerationService:
    def __init__(
        self,
        repository: GroupModerationRepository = group_moderation_repository,
        client_provider: Callable[[str], Awaitable[QQBotClient]] | None = None,
    ) -> None:
        self.repository = repository
        self._client_provider = client_provider or client_manager.get
        self._mute_coordinator = (
            group_mute_coordinator
            if repository is group_moderation_repository and client_provider is None
            else GroupMuteCoordinator(
                GroupMuteLeaseRepository(repository.path.with_name("group_mute_leases.db")),
                self._client_provider,
            )
        )

    async def set_official_mute(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        *,
        op: str,
        mute_expire_at: str = "",
        member_id: str | None = None,
        rule: str = "manual",
    ) -> dict[str, Any]:
        if op == "del":
            result = await self._mute_coordinator.release(
                bot_id, group_openid, member_openid, source="moderation"
            )
        else:
            result = await self._mute_coordinator.apply(
                bot_id,
                group_openid,
                member_openid,
                source="moderation",
                expire_at=mute_expire_at,
                detail=rule,
            )
        status_code = int(result.get("status_code", 0)) or None
        success = status_code is not None and 200 <= status_code < 300
        self.repository.add_log(
            bot_id=bot_id,
            member_id=member_id,
            group_openid=group_openid,
            member_openid=member_openid,
            action="official_unmute" if op == "del" else "official_mute",
            rule=rule,
            success=success,
            status_code=status_code,
            detail=str(result.get("data", "")),
        )
        return result

    async def _mute_for_special_rule(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        member_id: str,
        settings: dict[str, Any],
        *,
        action_key: str,
        rule: str,
        now: datetime,
    ) -> str | None:
        if not settings.get("use_official_mute", True) or settings.get(action_key) != "mute":
            return None
        mute_minutes = max(1, int(settings.get("special_rule_mute_minutes", 60)))
        expire_at = (now + timedelta(minutes=mute_minutes)).isoformat()
        result = await self.set_official_mute(
            bot_id,
            group_openid,
            member_openid,
            op="add",
            mute_expire_at=expire_at,
            member_id=member_id,
            rule=rule,
        )
        return expire_at if 200 <= int(result.get("status_code", 0)) < 300 else None

    async def handle_event(self, bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
        if event_type != "GROUP_MESSAGE_CREATE":
            return
        settings = self.repository.get_settings(bot_id)
        if not settings["enabled"] or is_bot_author(payload):
            return
        await self._handle_group_message(bot_id, payload, settings)

    async def _handle_group_message(self, bot_id: str, payload: dict[str, Any], settings: dict[str, Any]) -> None:
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        message_id = extract_message_id(payload)
        if not group_openid or not member_openid or not message_id:
            return
        if settings.get("exempt_admins", True) and extract_member_role(payload) in ADMIN_ROLES:
            return
        if group_verification_repository.get_pending_session(bot_id, group_openid, member_openid) is not None:
            return
        if not self.repository.claim_message(bot_id, message_id):
            return

        member_name = extract_member_name(payload)
        member = self.repository.ensure_member(bot_id, group_openid, member_openid, member_name)
        if member.get("trusted"):
            return
        now = utc_now_dt()
        content = extract_message_content(payload)

        if settings.get("retract_merged_messages") and is_merged_message(payload):
            client = await self._client_provider(bot_id)
            result = await client.retract_group_message(group_openid, message_id)
            status_code = int(result.get("status_code", 0)) or None
            success = status_code is not None and 200 <= status_code < 300
            detail = str(result.get("data", ""))
            self.repository.record_retraction(str(member["id"]), success=success, status_code=status_code, detail=detail, now=now.isoformat())
            self.repository.add_log(
                bot_id=bot_id, member_id=str(member["id"]), group_openid=group_openid,
                member_openid=member_openid, action="retract_merged", rule="merged_message",
                matched="message_type=102", message_excerpt=single_line(content),
                success=success, status_code=status_code, detail=detail,
            )
            blocked_until = await self._mute_for_special_rule(
                bot_id, group_openid, member_openid, str(member["id"]), settings,
                action_key="merged_message_action", rule="merged_message", now=now,
            )
            if blocked_until:
                self.repository.apply_penalty(
                    str(member["id"]), rule="merged_message", matched="message_type=102",
                    strike_count=int(member.get("strike_count", 0)),
                    penalty_level=int(member.get("penalty_level", 0)),
                    blocked_until=blocked_until, permanent=bool(member.get("permanent")),
                    member_name=member_name, now=now.isoformat(),
                )
            return

        if settings.get("retract_group_cards") and is_group_card(payload):
            client = await self._client_provider(bot_id)
            result = await client.retract_group_message(group_openid, message_id)
            status_code = int(result.get("status_code", 0)) or None
            success = status_code is not None and 200 <= status_code < 300
            detail = str(result.get("data", ""))
            ark = extract_ark_data(payload)
            fields = ark.get("fields") if isinstance(ark.get("fields"), dict) else {}
            matched = str(fields.get("nickname") or ark.get("prompt") or "group_card")
            self.repository.record_retraction(str(member["id"]), success=success, status_code=status_code, detail=detail, now=now.isoformat())
            self.repository.add_log(
                bot_id=bot_id, member_id=str(member["id"]), group_openid=group_openid,
                member_openid=member_openid, action="retract_group_card", rule="group_card",
                matched=matched, message_excerpt=single_line(content),
                success=success, status_code=status_code, detail=detail,
            )
            blocked_until = await self._mute_for_special_rule(
                bot_id, group_openid, member_openid, str(member["id"]), settings,
                action_key="group_card_action", rule="group_card", now=now,
            )
            if blocked_until:
                self.repository.apply_penalty(
                    str(member["id"]), rule="group_card", matched=matched,
                    strike_count=int(member.get("strike_count", 0)),
                    penalty_level=int(member.get("penalty_level", 0)),
                    blocked_until=blocked_until, permanent=bool(member.get("permanent")),
                    member_name=member_name, now=now.isoformat(),
                )
            return

        detection = detect_advertising(content, member_name or str(member.get("member_name") or ""), settings)
        blocked = active_block(member, now)
        penalty_applied = False
        penalty_minutes: int | None = None
        permanent = bool(member.get("permanent"))

        if detection is not None:
            last_violation = parse_time(member.get("last_violation_at"))
            cooldown = int(settings.get("escalation_cooldown_seconds", 60))
            cooldown_elapsed = last_violation is None or (now - last_violation).total_seconds() >= cooldown
            may_escalate = not permanent and (not blocked or (detection.source == "content" and cooldown_elapsed))
            if may_escalate:
                strike_count = int(member.get("strike_count", 0)) + 1
                permanent_after = int(settings.get("permanent_after", 5))
                durations = [int(v) for v in settings.get("penalty_minutes", []) if int(v) > 0]
                permanent = strike_count >= permanent_after
                level = permanent_after if permanent else min(strike_count, max(1, len(durations)))
                if permanent:
                    blocked_until = None
                    penalty_minutes = durations[-1] if durations else 10080
                else:
                    penalty_minutes = durations[min(strike_count - 1, len(durations) - 1)] if durations else 10
                    blocked_until = (now + timedelta(minutes=penalty_minutes)).isoformat()
                member = self.repository.apply_penalty(
                    str(member["id"]), rule=detection.rule, matched=detection.matched,
                    strike_count=strike_count, penalty_level=level, blocked_until=blocked_until,
                    permanent=permanent, member_name=member_name, now=now.isoformat(),
                )
                penalty_applied = True
            blocked = True

        if not blocked:
            return

        client = await self._client_provider(bot_id)
        result = await client.retract_group_message(group_openid, message_id)
        status_code = int(result.get("status_code", 0)) or None
        success = status_code is not None and 200 <= status_code < 300
        detail = str(result.get("data", ""))
        self.repository.record_retraction(str(member["id"]), success=success, status_code=status_code, detail=detail, now=now.isoformat())
        self.repository.add_log(
            bot_id=bot_id, member_id=str(member["id"]), group_openid=group_openid,
            member_openid=member_openid, action="retract_violation" if detection else "retract_blocked",
            rule=detection.rule if detection else str(member.get("last_rule") or "active_penalty"),
            matched=detection.matched if detection else "", message_excerpt=single_line(content),
            success=success, status_code=status_code, detail=detail,
        )

        official_mute_success = False
        if settings.get("use_official_mute", True) and (penalty_applied or permanent):
            if permanent:
                renewal_minutes = int(penalty_minutes or 10080)
                official_expiry = (now + timedelta(minutes=renewal_minutes)).isoformat()
            else:
                official_expiry = str(member.get("blocked_until") or "")
            if official_expiry:
                mute_result = await self.set_official_mute(
                    bot_id,
                    group_openid,
                    member_openid,
                    op="add",
                    mute_expire_at=official_expiry,
                    member_id=str(member["id"]),
                    rule=detection.rule if detection else str(member.get("last_rule") or "active_penalty"),
                )
                mute_code = int(mute_result.get("status_code", 0)) or None
                official_mute_success = mute_code is not None and 200 <= mute_code < 300

        if detection is not None and penalty_applied:
            last_warning = parse_time(member.get("last_warning_at"))
            warning_cooldown = int(settings.get("warning_cooldown_seconds", 30))
            if last_warning is None or (now - last_warning).total_seconds() >= warning_cooldown:
                label = member_name.strip() or "该成员"
                period = duration_text(penalty_minutes, False)
                if settings.get("use_official_mute", True) and official_mute_success:
                    prefix = "进入长期治理，" if permanent else ""
                    warning = single_line(f"警告：{label}触发群广告治理，{prefix}已由QQ官方禁言{period}。")
                else:
                    period = duration_text(penalty_minutes, permanent)
                    warning = single_line(f"警告：{label}触发群广告治理，当前{period}内发送的所有消息将自动撤回。")
                warning_result = await client.send_group_text(group_openid, warning)
                warning_code = int(warning_result.get("status_code", 0)) or None
                warning_success = warning_code is not None and 200 <= warning_code < 300
                self.repository.record_warning(str(member["id"]), now.isoformat())
                self.repository.add_log(
                    bot_id=bot_id, member_id=str(member["id"]), group_openid=group_openid,
                    member_openid=member_openid, action="send_warning", rule=detection.rule,
                    matched=detection.matched, success=warning_success, status_code=warning_code,
                    detail=str(warning_result.get("data", "")),
                )


group_moderation_service = GroupModerationService()
