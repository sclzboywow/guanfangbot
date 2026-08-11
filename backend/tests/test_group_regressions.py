import asyncio
from pathlib import Path
from typing import Any

from app.routers import group_management as group_management_router
from app.services.group_verification_repository import GroupVerificationRepository
from app.services.group_verification_service import GroupVerificationService


class FakeVerificationClient:
    def __init__(self, *, fail_send_numbers: set[int] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.retracted: list[tuple[str, str]] = []
        self.requests: list[tuple[str, str, object, object]] = []
        self.fail_send_numbers = fail_send_numbers or set()

    async def send_group_text(
        self,
        group_openid: str,
        content: str,
        *,
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
    ) -> dict[str, Any]:
        self.sent.append(
            {
                "group_openid": group_openid,
                "content": content,
                "msg_id": msg_id,
                "event_id": event_id,
                "msg_seq": msg_seq,
            }
        )
        status_code = 500 if len(self.sent) in self.fail_send_numbers else 200
        return {"status_code": status_code, "data": {"id": f"bot-{len(self.sent)}"}, "headers": {}}

    async def retract_group_message(self, group_openid: str, message_id: str) -> dict[str, Any]:
        self.retracted.append((group_openid, message_id))
        return {"status_code": 200, "data": {}, "headers": {}}

    async def request(self, method: str, path: str, query, body) -> dict[str, Any]:
        self.requests.append((method, path, query, body))
        return {"status_code": 200, "data": {}, "headers": {}}


def make_verification_service(
    tmp_path: Path,
    *,
    fail_send_numbers: set[int] | None = None,
) -> tuple[GroupVerificationRepository, FakeVerificationClient, GroupVerificationService]:
    repository = GroupVerificationRepository(tmp_path / "verification.db")
    repository.update_settings(
        "bot-1",
        enabled=True,
        math_enabled=True,
        custom_question_enabled=True,
        combination_mode="all",
        custom_question="本群口令是什么？",
        custom_answers=["星河"],
        custom_ignore_case=True,
        min_operand=1,
        max_operand=9,
        timeout_seconds=180,
        max_wrong_attempts=3,
        failure_mute_minutes=60,
        success_message="验证通过",
    )
    client = FakeVerificationClient(fail_send_numbers=fail_send_numbers)

    async def provider(_: str) -> FakeVerificationClient:
        return client

    return repository, client, GroupVerificationService(repository, provider)


def test_second_question_replies_to_first_correct_answer(tmp_path: Path) -> None:
    repository, client, service = make_verification_service(tmp_path)
    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MEMBER_ADD",
            {"id": "join-event", "d": {"group_openid": "group-1", "openid": "user-1"}},
        )
    )
    first = repository.list_sessions("bot-1")[0]
    assert first["challenge_type"] == "math"
    assert client.sent[0]["event_id"] == "join-event"

    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            {
                "d": {
                    "id": "first-answer",
                    "group_openid": "group-1",
                    "author": {"member_openid": "user-1"},
                    "content": str(first["answer"]),
                }
            },
        )
    )

    second = repository.get_session(str(first["id"]))
    assert second is not None
    assert second["status"] == "pending"
    assert second["challenge_type"] == "custom"
    assert second["completed_challenges"] == ["math"]
    assert client.sent[1]["msg_id"] == "first-answer"
    assert "本群口令是什么" in client.sent[1]["content"]

    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            {
                "d": {
                    "id": "second-answer",
                    "group_openid": "group-1",
                    "author": {"member_openid": "user-1"},
                    "content": "星河",
                }
            },
        )
    )
    verified = repository.get_session(str(first["id"]))
    assert verified is not None
    assert verified["status"] == "verified"
    assert client.sent[-1]["msg_id"] == "second-answer"


def test_failed_second_question_send_does_not_advance_state(tmp_path: Path) -> None:
    repository, client, service = make_verification_service(tmp_path, fail_send_numbers={2})
    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MEMBER_ADD",
            {"id": "join-event", "d": {"group_openid": "group-1", "openid": "user-1"}},
        )
    )
    first = repository.list_sessions("bot-1")[0]

    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            {
                "d": {
                    "id": "first-answer",
                    "group_openid": "group-1",
                    "author": {"member_openid": "user-1"},
                    "content": str(first["answer"]),
                }
            },
        )
    )

    current = repository.get_session(str(first["id"]))
    assert current is not None
    assert current["status"] == "pending"
    assert current["challenge_type"] == "math"
    assert current["completed_challenges"] == []
    assert current["question"] == first["question"]
    assert client.sent[1]["msg_id"] == "first-answer"


class FakeMuteCoordinator:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str, str]] = []

    async def release(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        *,
        source: str,
    ) -> dict[str, Any]:
        self.calls.append((bot_id, group_openid, member_openid, source))
        return self.result


class FakeGroupManagementService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[dict[str, Any]]]] = []

    async def set_member_mutes(
        self,
        bot_id: str,
        group_openid: str,
        members: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.calls.append((bot_id, group_openid, members))
        return {}


def test_manual_unmute_does_not_clear_other_active_mute_sources(monkeypatch) -> None:
    coordinator = FakeMuteCoordinator(
        {
            "status_code": 200,
            "data": {"message": "该来源没有有效禁言，无需解除"},
            "still_muted": True,
            "effective_expire_at": "2026-08-12T00:00:00+00:00",
        }
    )
    management = FakeGroupManagementService()
    monkeypatch.setattr(group_management_router, "group_mute_coordinator", coordinator)
    monkeypatch.setattr(group_management_router, "group_management_service", management)

    asyncio.run(group_management_router._release_manual_mute("bot", "group", "member"))

    assert coordinator.calls == [("bot", "group", "member", "manual")]
    assert management.calls == []


def test_manual_unmute_falls_back_for_untracked_official_mute(monkeypatch) -> None:
    coordinator = FakeMuteCoordinator(
        {
            "status_code": 200,
            "data": {"message": "该来源没有有效禁言，无需解除"},
            "still_muted": False,
            "effective_expire_at": "",
        }
    )
    management = FakeGroupManagementService()
    monkeypatch.setattr(group_management_router, "group_mute_coordinator", coordinator)
    monkeypatch.setattr(group_management_router, "group_management_service", management)

    asyncio.run(group_management_router._release_manual_mute("bot", "group", "member"))

    assert management.calls == [
        (
            "bot",
            "group",
            [{"op": "del", "member_openid": "member", "mute_expire_at": ""}],
        )
    ]
