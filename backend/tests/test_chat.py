import asyncio

from app.services.chat_repository import ChatRepository
from app.services.chat_service import ChatService, extract_message_content, extract_user_openid


def test_c2c_message_creates_contact_and_deduplicates(tmp_path) -> None:
    repository = ChatRepository(tmp_path / "chat.db")
    service = ChatService(repository)
    payload = {
        "id": "event-1",
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "message-1",
            "content": "你好，机器人",
            "timestamp": "2026-08-02T12:00:00+08:00",
            "author": {"user_openid": "user-openid-1", "username": "测试用户"},
        },
    }

    asyncio.run(service.handle_event("bot-1", "C2C_MESSAGE_CREATE", payload))
    asyncio.run(service.handle_event("bot-1", "C2C_MESSAGE_CREATE", payload))

    contact = repository.get_contact("bot-1", "user-openid-1")
    assert contact is not None
    assert contact["display_name"] == "测试用户"
    assert contact["unread_count"] == 1
    assert contact["active"] is True
    messages = repository.list_messages("bot-1", "user-openid-1", mark_read=False)
    assert len(messages) == 1
    assert messages[0]["content"] == "你好，机器人"


def test_loading_messages_marks_contact_read(tmp_path) -> None:
    repository = ChatRepository(tmp_path / "chat.db")
    repository.record_inbound(
        bot_id="bot-1",
        user_openid="user-1",
        content="第一条",
        qq_message_id="message-1",
    )
    assert repository.get_contact("bot-1", "user-1")["unread_count"] == 1
    repository.list_messages("bot-1", "user-1", mark_read=True)
    assert repository.get_contact("bot-1", "user-1")["unread_count"] == 0


def test_friend_relation_events_update_contact_state(tmp_path) -> None:
    repository = ChatRepository(tmp_path / "chat.db")
    service = ChatService(repository)

    for index, event_type in enumerate(("FRIEND_ADD", "C2C_MSG_REJECT", "FRIEND_DEL"), start=1):
        asyncio.run(service.handle_event(
            "bot-1",
            event_type,
            {"id": f"event-{index}", "d": {"openid": "user-1"}},
        ))

    contact = repository.get_contact("bot-1", "user-1")
    assert contact is not None
    assert contact["active"] is False
    assert contact["accepts_messages"] is False
    messages = repository.list_messages("bot-1", "user-1", mark_read=False)
    assert [item["kind"] for item in messages] == ["event", "event", "event"]


def test_outbound_message_and_reply_sequence(tmp_path) -> None:
    repository = ChatRepository(tmp_path / "chat.db")
    repository.record_inbound(
        bot_id="bot-1",
        user_openid="user-1",
        content="请回复",
        qq_message_id="inbound-1",
    )
    assert repository.next_reply_seq("bot-1", "inbound-1") == 1
    repository.record_outbound(
        bot_id="bot-1",
        user_openid="user-1",
        content="收到",
        success=True,
        qq_message_id="outbound-1",
        reply_to_msg_id="inbound-1",
        msg_seq=1,
        status_code=200,
    )
    assert repository.next_reply_seq("bot-1", "inbound-1") == 2
    assert repository.get_contact("bot-1", "user-1")["last_message_preview"] == "收到"


def test_event_extractors_cover_official_c2c_shape() -> None:
    data = {
        "author": {"user_openid": "openid-1"},
        "attachments": [{"filename": "photo.png", "content_type": "image/png"}],
    }
    assert extract_user_openid(data) == "openid-1"
    assert extract_message_content(data) == "[附件] photo.png"
