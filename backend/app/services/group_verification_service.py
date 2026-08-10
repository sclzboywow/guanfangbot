from __future__ import annotations

import asyncio
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.services.group_verification_repository import (
    GroupVerificationRepository,
    group_verification_repository,
)
from app.services.group_mute_repository import GroupMuteLeaseRepository, parse_time
from app.services.group_mute_service import GroupMuteCoordinator, group_mute_coordinator
from app.services.qqbot_client import QQBotClient, client_manager

logger = logging.getLogger(__name__)
REQUIRED_EVENTS = ("GROUP_MEMBER_ADD", "GROUP_MESSAGE_CREATE", "GROUP_MEMBER_REMOVE")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def single_line(value: str) -> str:
    """Collapse all whitespace so every outbound group message stays on one line."""
    return " ".join(str(value).split())


@dataclass(frozen=True)
class MathProblem:
    operand_a: int
    operand_b: int
    operator: str
    answer: int
    question: str


def generate_problem(min_operand: int, max_operand: int) -> MathProblem:
    if min_operand < 0 or max_operand < min_operand:
        raise ValueError("数学题范围无效")
    random = secrets.SystemRandom()
    a = random.randint(min_operand, max_operand)
    b = random.randint(min_operand, max_operand)
    if random.choice(("+", "-")) == "+":
        return MathProblem(a, b, "+", a + b, f"{a} + {b} = ?")
    high, low = max(a, b), min(a, b)
    return MathProblem(high, low, "-", high - low, f"{high} - {low} = ?")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _event_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("d")
    return data if isinstance(data, dict) else payload


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def extract_group_openid(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    group = _dict(data.get("group"))
    return _first_text(
        data.get("group_openid"),
        data.get("group_id"),
        group.get("openid"),
        group.get("id"),
    )


def extract_member_openid(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    author = _dict(data.get("author"))
    member = _dict(data.get("member"))
    member_user = _dict(member.get("user"))
    user = _dict(data.get("user"))
    return _first_text(
        data.get("member_openid"),
        data.get("group_member_openid"),
        data.get("user_openid"),
        data.get("openid"),
        author.get("member_openid"),
        author.get("group_member_openid"),
        author.get("user_openid"),
        author.get("openid"),
        author.get("id"),
        member.get("member_openid"),
        member.get("openid"),
        member.get("user_openid"),
        member_user.get("id"),
        member_user.get("openid"),
        user.get("id"),
        user.get("openid"),
    )


def extract_member_name(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    author = _dict(data.get("author"))
    member = _dict(data.get("member"))
    member_user = _dict(member.get("user"))
    user = _dict(data.get("user"))
    return _first_text(
        data.get("nick"),
        data.get("nickname"),
        data.get("username"),
        author.get("username"),
        author.get("nick"),
        author.get("nickname"),
        member.get("nick"),
        member.get("nickname"),
        member.get("username"),
        member_user.get("username"),
        member_user.get("nick"),
        user.get("username"),
        user.get("nick"),
        user.get("nickname"),
    )


def extract_message_id(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    return _first_text(data.get("id"), data.get("message_id"), payload.get("message_id"))


def extract_message_content(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    return str(data.get("content") or "")


def has_attachments(payload: dict[str, Any]) -> bool:
    data = _event_data(payload)
    attachments = data.get("attachments") or data.get("message_attachments") or []
    return bool(attachments)


def is_bot_author(payload: dict[str, Any]) -> bool:
    data = _event_data(payload)
    author = _dict(data.get("author"))
    return bool(author.get("bot"))


def event_id(payload: dict[str, Any]) -> str:
    return _first_text(payload.get("id"), _event_data(payload).get("event_id"))


class GroupVerificationService:
    def __init__(
        self,
        repository: GroupVerificationRepository = group_verification_repository,
        client_provider: Callable[[str], Awaitable[QQBotClient]] | None = None,
    ) -> None:
        self.repository = repository
        self._client_provider = client_provider or client_manager.get
        self._mute_coordinator = (
            group_mute_coordinator
            if repository is group_verification_repository and client_provider is None
            else GroupMuteCoordinator(
                GroupMuteLeaseRepository(repository.path.with_name("group_mute_leases.db")),
                self._client_provider,
            )
        )
        self._timeout_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._timeout_task and not self._timeout_task.done():
            return
        self._stop_event = asyncio.Event()
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
        self._timeout_task = None

    async def _timeout_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.process_expired_sessions()
            except Exception:
                logger.exception("group verification timeout scan failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def question_message(question: str) -> str:
        # 群聊发送 <@openid> 会被客户端原样显示，官方暂不支持真正 @ 渲染。
        return single_line(f"欢迎加入本群，请先完成验证：{question} 请直接发送数字答案。")

    @staticmethod
    def success_message(value: str) -> str:
        return single_line(value)

    @staticmethod
    def deadline(settings: dict[str, Any]) -> str:
        minutes = max(1, int(settings.get("verification_timeout_minutes", 3)))
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    @staticmethod
    def mute_expiry(settings: dict[str, Any]) -> str:
        minutes = max(1, int(settings.get("failure_mute_minutes", 1440)))
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    @staticmethod
    def _success(result: dict[str, Any]) -> bool:
        return 200 <= int(result.get("status_code", 0)) < 300

    async def _apply_verification_mute(
        self,
        session: dict[str, Any],
        settings: dict[str, Any],
        *,
        reason: str,
        mark_failed: bool,
    ) -> bool:
        expire_at = self.mute_expiry(settings)
        result = await self._mute_coordinator.apply(
            str(session["bot_id"]),
            str(session["group_openid"]),
            str(session["member_openid"]),
            source="verification",
            expire_at=expire_at,
            detail=reason,
        )
        success = self._success(result)
        if success:
            if mark_failed:
                self.repository.mark_failed(
                    str(session["id"]), reason=reason, muted_until=expire_at
                )
            else:
                self.repository.set_pending_mute(str(session["id"]), expire_at)
        else:
            self.repository.set_pending_mute(
                str(session["id"]),
                None,
                error=f"QQ官方禁言失败：{result.get('data', '')}",
            )
            if mark_failed:
                self.repository.clear_deadline(
                    str(session["id"]),
                    error=f"QQ官方禁言失败，已回退为继续撤回：{result.get('data', '')}",
                )
        self.repository.add_log(
            bot_id=str(session["bot_id"]),
            session_id=str(session["id"]),
            action=f"verification_mute:{reason}",
            success=success,
            status_code=int(result.get("status_code", 0)) or None,
            detail=str(result.get("data", "")),
        )
        return success

    async def _release_verification_mute(self, session: dict[str, Any]) -> dict[str, Any]:
        result = await self._mute_coordinator.release(
            str(session["bot_id"]),
            str(session["group_openid"]),
            str(session["member_openid"]),
            source="verification",
        )
        self.repository.add_log(
            bot_id=str(session["bot_id"]),
            session_id=str(session["id"]),
            action="verification_unmute",
            success=self._success(result),
            status_code=int(result.get("status_code", 0)) or None,
            detail=str(result.get("data", "")),
        )
        return result

    async def _send_question(
        self,
        *,
        bot_id: str,
        group_openid: str,
        session: dict[str, Any],
        reply_event_id: str | None = None,
    ) -> dict[str, Any]:
        client = await self._client_provider(bot_id)
        result = await client.send_group_text(
            group_openid,
            self.question_message(str(session["question"])),
            event_id=reply_event_id or None,
        )
        success = int(result.get("status_code", 500)) < 300
        self.repository.add_log(
            bot_id=bot_id,
            session_id=str(session["id"]),
            action="send_question",
            success=success,
            status_code=int(result.get("status_code", 0)) or None,
            detail=str(result.get("data", "")),
        )
        return result

    async def handle_event(self, bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
        settings = self.repository.get_settings(bot_id)
        if not settings["enabled"]:
            return
        try:
            if event_type == "GROUP_MEMBER_ADD":
                await self._handle_member_add(bot_id, payload, settings)
            elif event_type == "GROUP_MESSAGE_CREATE":
                await self._handle_group_message(bot_id, payload, settings)
            elif event_type == "GROUP_MEMBER_REMOVE":
                self._handle_member_remove(bot_id, payload)
        except Exception as exc:
            logger.exception("group verification event failed: %s", event_type)
            self.repository.add_log(
                bot_id=bot_id,
                session_id=None,
                action=f"event_error:{event_type}",
                success=False,
                detail=str(exc),
            )

    async def _handle_member_add(self, bot_id: str, payload: dict[str, Any], settings: dict[str, Any]) -> None:
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        if not group_openid or not member_openid:
            self.repository.add_log(
                bot_id=bot_id,
                session_id=None,
                action="member_add_missing_identity",
                success=False,
                detail="事件中缺少 group_openid 或 member_openid",
            )
            return
        manual_mode = settings.get("verification_mode") == "manual_mute"
        problem = (
            MathProblem(0, 0, "+", 0, "等待管理员审核")
            if manual_mode
            else generate_problem(int(settings["min_operand"]), int(settings["max_operand"]))
        )
        session = self.repository.create_or_reset_session(
            bot_id=bot_id,
            group_openid=group_openid,
            member_openid=member_openid,
            member_name=extract_member_name(payload),
            operand_a=problem.operand_a,
            operand_b=problem.operand_b,
            operator=problem.operator,
            answer=problem.answer,
            question=problem.question,
            joined_at=utc_now(),
            deadline_at=None if manual_mode else self.deadline(settings),
        )
        if manual_mode:
            await self._apply_verification_mute(
                session, settings, reason="manual_review", mark_failed=False
            )
            client = await self._client_provider(bot_id)
            result = await client.send_group_text(
                group_openid,
                single_line(str(settings.get("manual_review_message") or "等待管理员审核。")),
                event_id=event_id(payload) or None,
            )
            self.repository.add_log(
                bot_id=bot_id,
                session_id=str(session["id"]),
                action="send_manual_review_notice",
                success=self._success(result),
                status_code=int(result.get("status_code", 0)) or None,
                detail=str(result.get("data", "")),
            )
        else:
            await self._send_question(
                bot_id=bot_id,
                group_openid=group_openid,
                session=session,
                reply_event_id=event_id(payload),
            )

    async def _handle_group_message(
        self,
        bot_id: str,
        payload: dict[str, Any],
        settings: dict[str, Any],
    ) -> None:
        if is_bot_author(payload):
            return
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        if not group_openid or not member_openid:
            return
        session = self.repository.get_pending_session(bot_id, group_openid, member_openid)
        if session is None:
            return

        member_name = extract_member_name(payload)
        if member_name and not str(session.get("member_name") or "").strip():
            self.repository.update_member_name(str(session["id"]), member_name)

        message_id = extract_message_id(payload)
        if not self.repository.claim_message(bot_id, message_id, "verify_or_retract"):
            return

        content = extract_message_content(payload).strip()
        deadline = parse_time(str(session.get("deadline_at") or ""))
        timed_out = bool(deadline and deadline <= datetime.now(timezone.utc))
        correct = (
            not timed_out
            and settings.get("verification_mode") != "manual_mute"
            and not has_attachments(payload)
            and bool(re.fullmatch(r"[+-]?\d+", content))
            and int(content) == int(session["answer"])
        )
        if correct:
            release = await self._release_verification_mute(session)
            if not self._success(release):
                self.repository.set_pending_mute(
                    str(session["id"]),
                    session.get("muted_until"),
                    error=f"解除验证禁言失败：{release.get('data', '')}",
                )
                return
            self.repository.mark_verified(str(session["id"]))
            client = await self._client_provider(bot_id)
            result = await client.send_group_text(
                group_openid,
                self.success_message(str(settings["success_message"])),
                msg_id=message_id or None,
            )
            self.repository.add_log(
                bot_id=bot_id,
                session_id=str(session["id"]),
                action="verification_passed",
                success=int(result.get("status_code", 500)) < 300,
                status_code=int(result.get("status_code", 0)) or None,
                detail=str(result.get("data", "")),
            )
            return

        if not message_id:
            updated = self.repository.record_wrong_message(
                str(session["id"]),
                retracted=False,
                status_code=None,
                detail="事件缺少 message_id，无法撤回",
            )
            if updated is None:
                return
            if timed_out:
                await self._handle_verification_failure(updated, settings, reason="timeout")
            elif int(updated.get("wrong_attempts", 0)) >= max(
                1, int(settings.get("max_wrong_attempts", 3))
            ):
                await self._handle_verification_failure(
                    updated, settings, reason="too_many_errors"
                )
            return
        client = await self._client_provider(bot_id)
        result = await client.retract_group_message(group_openid, message_id)
        status_code = int(result.get("status_code", 0)) or None
        success = status_code is not None and 200 <= status_code < 300
        updated = self.repository.record_wrong_message(
            str(session["id"]),
            retracted=success,
            status_code=status_code,
            detail=str(result.get("data", "")),
        )
        if updated is None:
            return
        if timed_out:
            await self._handle_verification_failure(updated, settings, reason="timeout")
            return
        max_attempts = max(1, int(settings.get("max_wrong_attempts", 3)))
        if int(updated.get("wrong_attempts", 0)) >= max_attempts:
            await self._handle_verification_failure(updated, settings, reason="too_many_errors")

    async def _handle_verification_failure(
        self,
        session: dict[str, Any],
        settings: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        if settings.get("failure_action", "mute") == "mute":
            await self._apply_verification_mute(
                session, settings, reason=reason, mark_failed=True
            )
            return
        self.repository.clear_deadline(
            str(session["id"]),
            error="已达到验证限制，继续保持待验证并撤回非正确答案消息。",
        )
        self.repository.add_log(
            bot_id=str(session["bot_id"]),
            session_id=str(session["id"]),
            action=f"verification_limit:{reason}",
            success=True,
            detail="兼容模式：不禁言，继续撤回",
        )

    async def process_expired_sessions(self) -> int:
        sessions = self.repository.list_expired_pending(utc_now())
        processed = 0
        for session in sessions:
            settings = self.repository.get_settings(str(session["bot_id"]))
            if not settings.get("enabled") or settings.get("verification_mode") != "math":
                self.repository.clear_deadline(str(session["id"]))
                continue
            await self._handle_verification_failure(session, settings, reason="timeout")
            processed += 1
        return processed

    def _handle_member_remove(self, bot_id: str, payload: dict[str, Any]) -> None:
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        if group_openid and member_openid:
            self.repository.mark_removed(bot_id, group_openid, member_openid)
            self._mute_coordinator.repository.deactivate(
                bot_id, group_openid, member_openid, "verification"
            )

    async def reset_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError("验证记录不存在")
        settings = self.repository.get_settings(str(session["bot_id"]))
        release = await self._release_verification_mute(session)
        if not self._success(release):
            raise RuntimeError(f"解除验证禁言失败：{release.get('data', '')}")
        manual_mode = settings.get("verification_mode") == "manual_mute"
        problem = (
            MathProblem(0, 0, "+", 0, "等待管理员审核")
            if manual_mode
            else generate_problem(int(settings["min_operand"]), int(settings["max_operand"]))
        )
        updated = self.repository.replace_problem(
            session_id,
            operand_a=problem.operand_a,
            operand_b=problem.operand_b,
            operator=problem.operator,
            answer=problem.answer,
            question=problem.question,
            deadline_at=None if manual_mode else self.deadline(settings),
        )
        if updated is None:
            raise KeyError("验证记录不存在")
        if manual_mode:
            await self._apply_verification_mute(
                updated, settings, reason="manual_review", mark_failed=False
            )
            client = await self._client_provider(str(updated["bot_id"]))
            await client.send_group_text(
                str(updated["group_openid"]),
                single_line(str(settings.get("manual_review_message") or "等待管理员审核。")),
            )
        else:
            await self._send_question(
                bot_id=str(updated["bot_id"]),
                group_openid=str(updated["group_openid"]),
                session=updated,
            )
        return updated

    async def verify_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError("验证记录不存在")
        release = await self._release_verification_mute(session)
        if not self._success(release):
            raise RuntimeError(f"解除验证禁言失败：{release.get('data', '')}")
        self.repository.mark_verified(session_id)
        updated = self.repository.get_session(session_id)
        client = await self._client_provider(str(session["bot_id"]))
        settings = self.repository.get_settings(str(session["bot_id"]))
        result = await client.send_group_text(
            str(session["group_openid"]),
            self.success_message(str(settings["success_message"])),
        )
        self.repository.add_log(
            bot_id=str(session["bot_id"]),
            session_id=session_id,
            action="manual_verify",
            success=int(result.get("status_code", 500)) < 300,
            status_code=int(result.get("status_code", 0)) or None,
            detail=str(result.get("data", "")),
        )
        return updated or session

    async def close_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError("验证记录不存在")
        release = await self._release_verification_mute(session)
        if not self._success(release):
            raise RuntimeError(f"解除验证禁言失败：{release.get('data', '')}")
        self.repository.close_session(session_id)
        self.repository.add_log(
            bot_id=str(session["bot_id"]),
            session_id=session_id,
            action="manual_close",
            success=True,
            detail="结束验证并释放验证来源禁言",
        )
        return self.repository.get_session(session_id) or session


group_verification_service = GroupVerificationService()
