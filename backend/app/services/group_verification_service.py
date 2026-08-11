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
from app.services.group_mute_repository import GroupMuteLeaseRepository
from app.services.group_mute_service import GroupMuteCoordinator, group_mute_coordinator
from app.services.qqbot_client import QQBotClient, client_manager

logger = logging.getLogger(__name__)
REQUIRED_EVENTS = ("GROUP_MEMBER_ADD", "GROUP_MESSAGE_CREATE", "GROUP_MEMBER_REMOVE")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def single_line(value: str) -> str:
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
        text = str(value or "").strip()
        if text:
            return text
    return ""


def extract_group_openid(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    group = _dict(data.get("group"))
    return _first_text(data.get("group_openid"), data.get("group_id"), group.get("openid"), group.get("id"))


def extract_group_number(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    group = _dict(data.get("group"))
    for value in (data.get("group_id"), data.get("group_number"), group.get("id"), group.get("group_id")):
        text = str(value or "").strip()
        if text.isdigit():
            return text
    return ""


def extract_member_openid(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    author = _dict(data.get("author"))
    member = _dict(data.get("member"))
    member_user = _dict(member.get("user"))
    user = _dict(data.get("user"))
    return _first_text(
        data.get("member_openid"), data.get("group_member_openid"), data.get("user_openid"),
        data.get("openid"), author.get("member_openid"), author.get("group_member_openid"),
        author.get("user_openid"), author.get("openid"), author.get("id"),
        member.get("member_openid"), member.get("openid"), member.get("user_openid"),
        member_user.get("id"), member_user.get("openid"), user.get("id"), user.get("openid"),
    )


def extract_member_name(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    author = _dict(data.get("author"))
    member = _dict(data.get("member"))
    member_user = _dict(member.get("user"))
    user = _dict(data.get("user"))
    return _first_text(
        data.get("nick"), data.get("nickname"), data.get("username"), author.get("username"),
        author.get("nick"), author.get("nickname"), member.get("nick"), member.get("nickname"),
        member.get("username"), member_user.get("username"), member_user.get("nick"),
        user.get("username"), user.get("nick"), user.get("nickname"),
    )


def extract_message_id(payload: dict[str, Any]) -> str:
    data = _event_data(payload)
    return _first_text(data.get("id"), data.get("message_id"), payload.get("message_id"))


def extract_message_content(payload: dict[str, Any]) -> str:
    return str(_event_data(payload).get("content") or "")


def has_attachments(payload: dict[str, Any]) -> bool:
    data = _event_data(payload)
    return bool(data.get("attachments") or data.get("message_attachments") or [])


def is_bot_author(payload: dict[str, Any]) -> bool:
    return bool(_dict(_event_data(payload).get("author")).get("bot"))


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

    async def start(self) -> None:
        if self._timeout_task is None or self._timeout_task.done():
            self._timeout_task = asyncio.create_task(self._timeout_loop(), name="group-verification-timeouts")

    async def stop(self) -> None:
        task = self._timeout_task
        self._timeout_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _timeout_loop(self) -> None:
        while True:
            try:
                await self.process_timeouts()
                await self.process_expired_failure_mutes()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("group verification timeout sweep failed")
            await asyncio.sleep(15)

    @staticmethod
    def question_message(question: str, challenge_type: str = "math") -> str:
        hint = "请直接发送数字答案。" if challenge_type == "math" else "请直接发送答案文字。"
        return single_line(f"欢迎加入本群，请先完成验证：{question} {hint}")

    @staticmethod
    def success_message(value: str) -> str:
        return single_line(value)

    @staticmethod
    def _deadline(settings: dict[str, Any]) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=int(settings["timeout_seconds"]))).isoformat()

    @staticmethod
    def _challenge_order(settings: dict[str, Any]) -> list[str]:
        enabled: list[str] = []
        if settings.get("math_enabled"):
            enabled.append("math")
        if settings.get("custom_question_enabled"):
            enabled.append("custom")
        if len(enabled) > 1 and settings.get("combination_mode") == "random_one":
            return [secrets.choice(enabled)]
        return enabled

    @staticmethod
    def _challenge(settings: dict[str, Any], challenge_type: str) -> dict[str, Any]:
        if challenge_type == "custom":
            return {
                "operand_a": 0,
                "operand_b": 0,
                "operator": "",
                "answer": 0,
                "question": str(settings["custom_question"]),
                "challenge_type": "custom",
                "accepted_answers": list(settings.get("custom_answers") or []),
            }
        problem = generate_problem(int(settings["min_operand"]), int(settings["max_operand"]))
        return {
            "operand_a": problem.operand_a,
            "operand_b": problem.operand_b,
            "operator": problem.operator,
            "answer": problem.answer,
            "question": problem.question,
            "challenge_type": "math",
            "accepted_answers": [],
        }

    async def _send_question(
        self,
        *,
        bot_id: str,
        group_openid: str,
        session: dict[str, Any],
        reply_message_id: str | None = None,
        reply_event_id: str | None = None,
    ) -> dict[str, Any]:
        client = await self._client_provider(bot_id)
        result = await client.send_group_text(
            group_openid,
            self.question_message(str(session["question"]), str(session.get("challenge_type") or "math")),
            msg_id=reply_message_id or None,
            event_id=reply_event_id or None,
        )
        self.repository.add_log(
            bot_id=bot_id,
            session_id=str(session["id"]),
            action="send_question",
            success=int(result.get("status_code", 500)) < 300,
            status_code=int(result.get("status_code", 0)) or None,
            detail=str(result.get("data", "")),
        )
        return result

    async def _set_member_mute(self, session: dict[str, Any], op: str, expire_at: str = "") -> bool:
        if op == "del":
            result = await self._mute_coordinator.release(
                str(session["bot_id"]), str(session["group_openid"]),
                str(session["member_openid"]), source="verification",
            )
        else:
            result = await self._mute_coordinator.apply(
                str(session["bot_id"]), str(session["group_openid"]),
                str(session["member_openid"]), source="verification",
                expire_at=expire_at, detail="入群验证失败",
            )
        success = int(result.get("status_code", 500)) < 300
        self.repository.add_log(
            bot_id=str(session["bot_id"]), session_id=str(session["id"]),
            action="verification_unmute" if op == "del" else "verification_failure_mute",
            success=success, status_code=int(result.get("status_code", 0)) or None,
            detail=str(result.get("data", "")),
        )
        return success

    async def _fail_session(self, session: dict[str, Any], reason: str, settings: dict[str, Any]) -> bool:
        mute_expire_at = (
            datetime.now(timezone.utc) + timedelta(minutes=int(settings["failure_mute_minutes"]))
        ).isoformat()
        if not self.repository.mark_failed(str(session["id"]), reason=reason, mute_expire_at=mute_expire_at):
            return False
        if not await self._set_member_mute(session, "add", mute_expire_at):
            self.repository.restore_pending_after_mute_error(
                str(session["id"]), str(session.get("deadline_at") or "") or None,
            )
            return False
        return True

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
                bot_id=bot_id, session_id=None, action=f"event_error:{event_type}",
                success=False, detail=str(exc),
            )

    async def _handle_member_add(self, bot_id: str, payload: dict[str, Any], settings: dict[str, Any]) -> None:
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        if not group_openid or not member_openid:
            self.repository.add_log(
                bot_id=bot_id, session_id=None, action="member_add_missing_identity",
                success=False, detail="事件中缺少 group_openid 或 member_openid",
            )
            return
        required = self._challenge_order(settings)
        if not required:
            return
        challenge = self._challenge(settings, required[0])
        session = self.repository.create_or_reset_session(
            bot_id=bot_id, group_openid=group_openid, member_openid=member_openid,
            member_name=extract_member_name(payload), required_challenges=required,
            completed_challenges=[], joined_at=utc_now(), deadline_at=self._deadline(settings),
            **challenge,
        )
        await self._send_question(
            bot_id=bot_id, group_openid=group_openid, session=session,
            reply_event_id=event_id(payload),
        )

    @staticmethod
    def _is_correct(content: str, session: dict[str, Any], settings: dict[str, Any]) -> bool:
        if str(session.get("challenge_type")) == "custom":
            expected = [single_line(item) for item in session.get("accepted_answers") or []]
            actual = single_line(content)
            if settings.get("custom_ignore_case"):
                expected = [item.casefold() for item in expected]
                actual = actual.casefold()
            return bool(actual and actual in expected)
        return bool(re.fullmatch(r"[+-]?\d+", content)) and int(content) == int(session["answer"])

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
        session = self.repository.get_unverified_session(bot_id, group_openid, member_openid)
        if session is None:
            return
        member_name = extract_member_name(payload)
        if member_name and not str(session.get("member_name") or "").strip():
            self.repository.update_member_name(str(session["id"]), member_name)
        message_id = extract_message_id(payload)
        if not self.repository.claim_message(bot_id, message_id, "verify_or_retract"):
            return
        content = extract_message_content(payload).strip()
        correct = not has_attachments(payload) and self._is_correct(content, session, settings)
        if correct:
            completed = list(session.get("completed_challenges") or [])
            current = str(session.get("challenge_type") or "math")
            if current not in completed:
                completed.append(current)
            remaining = [item for item in session.get("required_challenges") or [] if item not in completed]
            if remaining:
                challenge = self._challenge(settings, remaining[0])
                next_session = {**session, **challenge}
                send_result = await self._send_question(
                    bot_id=bot_id,
                    group_openid=group_openid,
                    session=next_session,
                    reply_message_id=message_id or None,
                )
                if int(send_result.get("status_code", 500)) >= 300:
                    return
                self.repository.replace_problem(
                    str(session["id"]),
                    required_challenges=list(session.get("required_challenges") or []),
                    completed_challenges=completed,
                    deadline_at=self._deadline(settings),
                    reset_attempts=False,
                    **challenge,
                )
                return
            if str(session.get("status") or "") == "failed":
                # Failure mute may still be active; release before treating as verified.
                await self._set_member_mute(session, "del")
            self.repository.mark_verified(str(session["id"]))
            client = await self._client_provider(bot_id)
            result = await client.send_group_text(
                group_openid, self.success_message(str(settings["success_message"])), msg_id=message_id or None,
            )
            self.repository.add_log(
                bot_id=bot_id, session_id=str(session["id"]), action="verification_passed",
                success=int(result.get("status_code", 500)) < 300,
                status_code=int(result.get("status_code", 0)) or None, detail=str(result.get("data", "")),
            )
            return

        retracted = False
        status_code: int | None = None
        detail = "事件缺少 message_id，无法撤回"
        if message_id:
            client = await self._client_provider(bot_id)
            result = await client.retract_group_message(group_openid, message_id)
            status_code = int(result.get("status_code", 0)) or None
            retracted = status_code is not None and 200 <= status_code < 300
            detail = str(result.get("data", ""))
        if str(session.get("status") or "") == "failed":
            # Still unverified after punishment mute: keep retracting, do not "free pass".
            self.repository.add_log(
                bot_id=bot_id, session_id=str(session["id"]), action="retract_message",
                success=retracted, status_code=status_code, detail=detail,
            )
            return
        updated = self.repository.record_wrong_message(
            str(session["id"]), retracted=retracted, status_code=status_code, detail=detail,
        )
        if updated and int(updated["wrong_attempts"]) >= int(settings["max_wrong_attempts"]):
            await self._fail_session(updated, "wrong_attempt_limit", settings)

    def _handle_member_remove(self, bot_id: str, payload: dict[str, Any]) -> None:
        group_openid = extract_group_openid(payload)
        member_openid = extract_member_openid(payload)
        if group_openid and member_openid:
            self.repository.mark_removed(bot_id, group_openid, member_openid)
            self._mute_coordinator.repository.deactivate(
                bot_id, group_openid, member_openid, "verification"
            )

    async def process_timeouts(self) -> int:
        processed = 0
        for session in self.repository.list_expired_pending():
            settings = self.repository.get_settings(str(session["bot_id"]))
            if await self._fail_session(session, "timeout", settings):
                processed += 1
        return processed

    async def process_expired_failure_mutes(self) -> int:
        """After failure mute ends, reopen verification so members cannot chat freely."""
        processed = 0
        for session in self.repository.list_expired_failure_mutes():
            try:
                if await self._reopen_after_failure_mute(session):
                    processed += 1
            except Exception:
                logger.exception(
                    "reopen verification after failure mute failed session=%s",
                    session.get("id"),
                )
        return processed

    async def _reopen_after_failure_mute(self, session: dict[str, Any]) -> bool:
        if str(session.get("status") or "") != "failed":
            return False
        settings = self.repository.get_settings(str(session["bot_id"]))
        if not settings.get("enabled"):
            return False
        required = self._challenge_order(settings)
        if not required:
            return False
        # Official mute may already have expired; clear local lease / leftover mute.
        await self._set_member_mute(session, "del")
        challenge = self._challenge(settings, required[0])
        updated = self.repository.replace_problem(
            str(session["id"]),
            required_challenges=required,
            completed_challenges=[],
            deadline_at=self._deadline(settings),
            reset_attempts=True,
            **challenge,
        )
        if updated is None:
            return False
        await self._send_question(
            bot_id=str(updated["bot_id"]),
            group_openid=str(updated["group_openid"]),
            session=updated,
        )
        self.repository.add_log(
            bot_id=str(updated["bot_id"]),
            session_id=str(updated["id"]),
            action="reopen_after_failure_mute",
            success=True,
            detail="禁言结束，已重新出题，需完成验证后才能正常发言",
        )
        return True

    async def reset_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError("验证记录不存在")
        settings = self.repository.get_settings(str(session["bot_id"]))
        required = self._challenge_order(settings)
        if not required:
            raise ValueError("请至少启用一种验证方式")
        if not await self._set_member_mute(session, "del"):
            raise RuntimeError("QQ 官方解除禁言失败，未重新出题")
        challenge = self._challenge(settings, required[0])
        updated = self.repository.replace_problem(
            session_id, required_challenges=required, completed_challenges=[],
            deadline_at=self._deadline(settings), reset_attempts=True, **challenge,
        )
        if updated is None:
            raise KeyError("验证记录不存在")
        await self._send_question(
            bot_id=str(updated["bot_id"]), group_openid=str(updated["group_openid"]), session=updated,
        )
        return updated

    async def verify_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError("验证记录不存在")
        if not await self._set_member_mute(session, "del"):
            raise RuntimeError("QQ 官方解除禁言失败，未标记通过")
        self.repository.mark_verified(session_id)
        settings = self.repository.get_settings(str(session["bot_id"]))
        client = await self._client_provider(str(session["bot_id"]))
        result = await client.send_group_text(
            str(session["group_openid"]), self.success_message(str(settings["success_message"])),
        )
        self.repository.add_log(
            bot_id=str(session["bot_id"]), session_id=session_id, action="manual_verify",
            success=int(result.get("status_code", 500)) < 300,
            status_code=int(result.get("status_code", 0)) or None, detail=str(result.get("data", "")),
        )
        return self.repository.get_session(session_id) or session

    async def close_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get_session(session_id)
        if session is None:
            raise KeyError("验证记录不存在")
        if not await self._set_member_mute(session, "del"):
            raise RuntimeError("QQ 官方解除验证来源禁言失败，未结束验证")
        self.repository.close_session(session_id)
        self.repository.add_log(
            bot_id=str(session["bot_id"]), session_id=session_id,
            action="manual_close", success=True,
            detail="结束验证并释放验证来源禁言",
        )
        return self.repository.get_session(session_id) or session


group_verification_service = GroupVerificationService()
