import asyncio
from pathlib import Path

from app.services.group_moderation_repository import GroupModerationRepository
from app.services.group_moderation_service import GroupModerationService, detect_advertising


class FakeClient:
    def __init__(self) -> None:
        self.retracted: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str]] = []

    async def retract_group_message(self, group_openid: str, message_id: str):
        self.retracted.append((group_openid, message_id))
        return {"status_code": 200, "data": {}}

    async def send_group_text(self, group_openid: str, content: str, **_kwargs):
        self.sent.append((group_openid, content))
        return {"status_code": 200, "data": {}}


def message_payload(
    content: str,
    *,
    message_id: str,
    member_name: str = "普通成员",
    member_role: str = "member",
) -> dict:
    return {
        "d": {
            "group_openid": "group-1",
            "id": message_id,
            "content": content,
            "author": {
                "member_openid": "member-1",
                "username": member_name,
                "member_role": member_role,
            },
        }
    }


def enabled_settings(repository: GroupModerationRepository, **values):
    return repository.update_settings("bot-1", enabled=True, **values)


def test_advertising_detection_rules(tmp_path: Path) -> None:
    repository = GroupModerationRepository(tmp_path / "moderation.db")
    settings = enabled_settings(repository)

    assert detect_advertising("联系电话 138-0013-8000", "普通成员", settings).rule == "mobile_phone"
    assert detect_advertising("座机 010-12345678", "普通成员", settings).rule == "landline_phone"
    assert detect_advertising("微信 abcdef12", "普通成员", settings).rule == "wechat"
    assert detect_advertising("低息贷款当天放款", "普通成员", settings).rule == "content_keyword"
    assert detect_advertising("正常交流", "专业发票办理", settings).rule == "nickname_keyword"
    assert detect_advertising("订单编号 202608020123", "普通成员", settings) is None
    assert detect_advertising("讨论微信支付接口", "普通成员", settings) is None


def test_violation_warns_and_blocks_following_messages(tmp_path: Path) -> None:
    repository = GroupModerationRepository(tmp_path / "moderation.db")
    enabled_settings(repository)
    client = FakeClient()

    async def provider(_bot_id: str):
        return client

    service = GroupModerationService(repository, provider)
    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", message_payload("加微信 abcdef12", message_id="m1")))

    member = repository.get_member("bot-1", "group-1", "member-1")
    assert member is not None
    assert member["strike_count"] == 1
    assert member["permanent"] is False
    assert len(client.retracted) == 1
    assert len(client.sent) == 1
    assert "\n" not in client.sent[0][1]
    assert "10分钟" in client.sent[0][1]

    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", message_payload("正常聊天", message_id="m2")))
    assert len(client.retracted) == 2
    assert len(client.sent) == 1


def test_repeated_advertising_reaches_permanent_stage(tmp_path: Path) -> None:
    repository = GroupModerationRepository(tmp_path / "moderation.db")
    enabled_settings(repository, escalation_cooldown_seconds=0, warning_cooldown_seconds=0)
    client = FakeClient()

    async def provider(_bot_id: str):
        return client

    service = GroupModerationService(repository, provider)
    for index in range(5):
        asyncio.run(service.handle_event(
            "bot-1",
            "GROUP_MESSAGE_CREATE",
            message_payload("贷款放款", message_id=f"m-{index}"),
        ))

    member = repository.get_member("bot-1", "group-1", "member-1")
    assert member is not None
    assert member["strike_count"] == 5
    assert member["permanent"] is True
    assert len(client.retracted) == 5
    assert "永久" in client.sent[-1][1]


def test_duplicate_message_is_processed_once(tmp_path: Path) -> None:
    repository = GroupModerationRepository(tmp_path / "moderation.db")
    enabled_settings(repository)
    client = FakeClient()

    async def provider(_bot_id: str):
        return client

    service = GroupModerationService(repository, provider)
    payload = message_payload("电话 13800138000", message_id="same-message")
    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", payload))
    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", payload))
    assert len(client.retracted) == 1


def test_admin_exemption_and_manual_controls(tmp_path: Path) -> None:
    repository = GroupModerationRepository(tmp_path / "moderation.db")
    enabled_settings(repository)
    client = FakeClient()

    async def provider(_bot_id: str):
        return client

    service = GroupModerationService(repository, provider)
    asyncio.run(service.handle_event(
        "bot-1",
        "GROUP_MESSAGE_CREATE",
        message_payload("贷款", message_id="admin-message", member_role="admin"),
    ))
    assert client.retracted == []

    member = repository.ensure_member("bot-1", "group-1", "member-1", "成员")
    repository.make_permanent(str(member["id"]))
    assert repository.get_member_by_id(str(member["id"]))["permanent"] is True
    repository.set_trusted(str(member["id"]), True)
    trusted = repository.get_member_by_id(str(member["id"]))
    assert trusted["trusted"] is True
    assert trusted["permanent"] is False
    repository.release_member(str(member["id"]), reset_strikes=True)
    reset = repository.get_member_by_id(str(member["id"]))
    assert reset["strike_count"] == 0
