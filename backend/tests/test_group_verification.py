import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from app.services.group_verification_repository import GroupVerificationRepository
from app.services.group_verification_service import GroupVerificationService, single_line


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.retracted: list[tuple[str, str]] = []

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
        return {"status_code": 200, "data": {"id": f"bot-{len(self.sent)}"}, "headers": {}}

    async def retract_group_message(self, group_openid: str, message_id: str) -> dict[str, Any]:
        self.retracted.append((group_openid, message_id))
        return {"status_code": 200, "data": {}, "headers": {}}


def make_service(tmp_path: Path):
    repository = GroupVerificationRepository(tmp_path / "verification.db")
    repository.update_settings("bot-1", enabled=True, min_operand=1, max_operand=9)
    client = FakeClient()

    async def provider(_: str):
        return client

    return repository, client, GroupVerificationService(repository, provider)


def test_single_line_collapses_all_whitespace() -> None:
    assert single_line("欢迎\n加入\t群聊") == "欢迎 加入 群聊"


def test_join_wrong_message_then_correct_answer(tmp_path: Path) -> None:
    repository, client, service = make_service(tmp_path)
    repository.update_settings(
        "bot-1",
        enabled=True,
        min_operand=1,
        max_operand=9,
        success_message="欢迎通过验证，现在可以聊天啦。",
    )

    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MEMBER_ADD",
            {
                "id": "event-join-1",
                "d": {
                    "group_openid": "group-1",
                    "openid": "user-1",
                    "nick": "测试成员",
                },
            },
        )
    )

    sessions = repository.list_sessions("bot-1")
    assert len(sessions) == 1
    session = sessions[0]
    assert session["status"] == "pending"
    assert client.sent[0]["event_id"] == "event-join-1"
    assert "\n" not in client.sent[0]["content"]
    assert "\r" not in client.sent[0]["content"]

    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            {
                "d": {
                    "id": "msg-wrong",
                    "group_openid": "group-1",
                    "author": {"member_openid": "user-1", "bot": False},
                    "content": "不是答案",
                }
            },
        )
    )
    assert client.retracted == [("group-1", "msg-wrong")]
    pending = repository.get_session(str(session["id"]))
    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["wrong_attempts"] == 1
    assert pending["retracted_messages"] == 1

    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            {
                "d": {
                    "id": "msg-correct",
                    "group_openid": "group-1",
                    "author": {"member_openid": "user-1", "bot": False},
                    "content": f" {session['answer']} ",
                    "attachments": [],
                }
            },
        )
    )
    verified = repository.get_session(str(session["id"]))
    assert verified is not None
    assert verified["status"] == "verified"
    assert client.retracted == [("group-1", "msg-wrong")]
    assert client.sent[-1]["msg_id"] == "msg-correct"
    assert client.sent[-1]["content"] == "欢迎通过验证，现在可以聊天啦。"
    assert "\n" not in client.sent[-1]["content"]


def test_attachment_is_not_accepted_as_answer(tmp_path: Path) -> None:
    repository, client, service = make_service(tmp_path)
    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MEMBER_ADD",
            {"id": "join", "d": {"group_openid": "g", "openid": "u"}},
        )
    )
    session = repository.list_sessions("bot-1")[0]
    asyncio.run(
        service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            {
                "d": {
                    "id": "with-file",
                    "group_openid": "g",
                    "author": {"member_openid": "u"},
                    "content": str(session["answer"]),
                    "attachments": [{"url": "https://example.invalid/file"}],
                }
            },
        )
    )
    assert client.retracted == [("g", "with-file")]
    assert repository.get_session(str(session["id"]))["status"] == "pending"


def test_duplicate_message_is_processed_once(tmp_path: Path) -> None:
    repository, client, service = make_service(tmp_path)
    asyncio.run(service.handle_event("bot-1", "GROUP_MEMBER_ADD", {"d": {"group_openid": "g", "openid": "u"}}))
    payload = {
        "d": {
            "id": "duplicate",
            "group_openid": "g",
            "author": {"member_openid": "u"},
            "content": "wrong",
        }
    }
    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", payload))
    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", payload))
    assert client.retracted == [("g", "duplicate")]


def test_member_remove_closes_pending_session(tmp_path: Path) -> None:
    repository, _, service = make_service(tmp_path)
    asyncio.run(service.handle_event("bot-1", "GROUP_MEMBER_ADD", {"d": {"group_openid": "g", "openid": "u"}}))
    asyncio.run(service.handle_event("bot-1", "GROUP_MEMBER_REMOVE", {"d": {"group_openid": "g", "openid": "u"}}))
    assert repository.list_sessions("bot-1")[0]["status"] == "removed"


def test_repository_state_persists(tmp_path: Path) -> None:
    path = tmp_path / "verification.db"
    repository = GroupVerificationRepository(path)
    repository.update_settings("bot-1", enabled=True, min_operand=2, max_operand=8)
    repository.create_or_reset_session(
        bot_id="bot-1",
        group_openid="g",
        member_openid="u",
        member_name="member",
        operand_a=2,
        operand_b=3,
        operator="+",
        answer=5,
        question="2 + 3 = ?",
    )
    reopened = GroupVerificationRepository(path)
    assert reopened.get_settings("bot-1")["enabled"] is True
    assert reopened.get_pending_session("bot-1", "g", "u")["answer"] == 5


def test_existing_database_adds_success_message_column(tmp_path: Path) -> None:
    path = tmp_path / "legacy-verification.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE verification_settings (
                bot_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                min_operand INTEGER NOT NULL DEFAULT 1,
                max_operand INTEGER NOT NULL DEFAULT 20,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO verification_settings(bot_id, enabled, min_operand, max_operand, updated_at) "
            "VALUES ('bot-1', 1, 2, 8, '2026-08-07T00:00:00+00:00')"
        )

    repository = GroupVerificationRepository(path)
    settings = repository.get_settings("bot-1")
    assert settings["success_message"] == "验证通过，你现在可以正常发言。"
