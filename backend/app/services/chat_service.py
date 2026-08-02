from __future__ import annotations

from typing import Any

from app.services.chat_repository import ChatRepository, chat_repository

CHAT_EVENTS = {
    "C2C_MESSAGE_CREATE",
    "FRIEND_ADD",
    "FRIEND_DEL",
    "C2C_MSG_REJECT",
    "C2C_MSG_RECEIVE",
}
REQUIRED_EVENTS = tuple(sorted(CHAT_EVENTS))


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def extract_user_openid(data: dict[str, Any]) -> str:
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return _first_text(
        author.get("user_openid"),
        author.get("openid"),
        data.get("user_openid"),
        data.get("openid"),
        user.get("user_openid"),
        user.get("openid"),
        user.get("id"),
    )


def extract_display_name(data: dict[str, Any]) -> str:
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return _first_text(
        author.get("username"),
        author.get("nickname"),
        author.get("name"),
        data.get("username"),
        data.get("nickname"),
        user.get("username"),
        user.get("nickname"),
        user.get("name"),
    )[:80]


def extract_message_content(data: dict[str, Any]) -> str:
    content = str(data.get("content") or "").strip()
    if content:
        return content
    attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
    labels: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        filename = _first_text(attachment.get("filename"), attachment.get("name"))
        content_type = _first_text(attachment.get("content_type"), attachment.get("type"))
        if filename:
            labels.append(f"[附件] {filename}")
        elif content_type:
            labels.append(f"[{content_type}]")
        else:
            labels.append("[附件]")
    return "\n".join(labels) or "[非文本消息]"


class ChatService:
    def __init__(self, repository: ChatRepository = chat_repository) -> None:
        self.repository = repository

    async def handle_event(self, bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
        if event_type not in CHAT_EVENTS:
            return
        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        user_openid = extract_user_openid(data)
        if not user_openid:
            return

        event_id = str(payload.get("id") or "").strip()
        display_name = extract_display_name(data)
        created_at = _first_text(data.get("timestamp"), data.get("event_ts")) or None

        if event_type == "C2C_MESSAGE_CREATE":
            self.repository.record_inbound(
                bot_id=bot_id,
                user_openid=user_openid,
                content=extract_message_content(data),
                qq_message_id=str(data.get("id") or "").strip(),
                event_id=event_id,
                display_name=display_name,
                created_at=created_at,
            )
            return

        self.repository.record_relation_event(
            bot_id=bot_id,
            user_openid=user_openid,
            event_type=event_type,
            event_id=event_id,
            display_name=display_name,
            created_at=created_at,
        )


chat_service = ChatService()
