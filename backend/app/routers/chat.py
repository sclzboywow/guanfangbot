from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.bot_repository import bot_repository
from app.services.chat_repository import chat_repository
from app.services.chat_service import REQUIRED_EVENTS
from app.services.qqbot_client import client_manager

router = APIRouter(prefix="/chat", tags=["chat"])
PASSIVE_REPLY_WINDOW = timedelta(minutes=55)
PASSIVE_EXPIRED_CODES = {304103, 40034005, 40034024, 40034128}


class ChatSendRequest(BaseModel):
    bot_id: str = Field(min_length=1, max_length=128)
    user_openid: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("bot_id", "user_openid")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char.isspace() for char in cleaned):
            raise ValueError("标识不能为空或包含空格")
        return cleaned

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        cleaned = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not cleaned:
            raise ValueError("消息内容不能为空")
        return cleaned


class ChatContactRenameRequest(BaseModel):
    bot_id: str = Field(min_length=1, max_length=128)
    user_openid: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("bot_id", "user_openid")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char.isspace() for char in cleaned):
            raise ValueError("标识不能为空或包含空格")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        cleaned = " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split()).strip()
        if not cleaned:
            raise ValueError("昵称不能为空")
        return cleaned[:80]


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _error_code(result: dict[str, Any]) -> int:
    data = result.get("data")
    if not isinstance(data, dict):
        return 0
    value = data.get("code", data.get("error_code", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _error_detail(result: dict[str, Any]) -> str:
    data = result.get("data")
    if isinstance(data, dict):
        return str(data.get("message") or data.get("detail") or data)[:1200]
    return str(data or "QQ 单聊消息发送失败")[:1200]


@router.get("/status")
def chat_status(bot_id: str = Query(...), user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    configured = set(bot.event_scopes)
    return {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "app_id": bot.app_id,
        "contacts": chat_repository.list_contacts(bot_id),
        "counts": chat_repository.counts(bot_id),
        "required_events": [
            {"code": code, "configured": code in configured}
            for code in REQUIRED_EVENTS
        ],
        "requirements_ready": all(code in configured for code in REQUIRED_EVENTS),
        "official_friend_list_supported": False,
        "source_note": (
            "QQ 官方接口没有提供全量好友列表，也无法按 openid 查询用户昵称。"
            "若单聊/好友事件里带有昵称会自动写入；也可在本页手动设置备注昵称。"
        ),
    }


@router.patch("/contacts")
def rename_chat_contact(
    payload: ChatContactRenameRequest,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(payload.bot_id, user)
    contact = chat_repository.set_display_name(
        payload.bot_id,
        payload.user_openid,
        payload.display_name,
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return {"contact": contact}


@router.get("/messages")
def chat_messages(
    bot_id: str = Query(...),
    user_openid: str = Query(...),
    limit: int = Query(default=100, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    contact = chat_repository.get_contact(bot_id, user_openid)
    if contact is None:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return {
        "contact": contact,
        "messages": chat_repository.list_messages(
            bot_id,
            user_openid,
            limit=limit,
            before_id=before_id,
            mark_read=before_id is None,
        ),
    }


@router.post("/messages")
async def send_chat_message(payload: ChatSendRequest, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    require_owned_bot(payload.bot_id, user)
    contact = chat_repository.get_contact(payload.bot_id, payload.user_openid)
    if contact is None:
        raise HTTPException(status_code=404, detail="联系人不存在；请先让用户添加机器人好友或发起单聊")
    if not contact.get("active"):
        raise HTTPException(status_code=409, detail="该用户已删除机器人好友，无法继续发送单聊消息")

    context = chat_repository.latest_reply_context(payload.bot_id, payload.user_openid) or {}
    received_at = _parse_time(context.get("received_at"))
    reply_msg_id = str(context.get("msg_id") or "")
    use_passive = bool(
        reply_msg_id
        and received_at
        and datetime.now(timezone.utc) - received_at <= PASSIVE_REPLY_WINDOW
    )
    msg_seq = chat_repository.next_reply_seq(payload.bot_id, reply_msg_id) if use_passive else None

    client = await client_manager.get(payload.bot_id)
    result = await client.send_c2c_text(
        payload.user_openid,
        payload.content,
        msg_id=reply_msg_id if use_passive else None,
        msg_seq=msg_seq or 1,
    )
    delivery_mode = "passive" if use_passive else "active"

    if use_passive and result.get("status_code", 500) >= 400 and _error_code(result) in PASSIVE_EXPIRED_CODES:
        result = await client.send_c2c_text(payload.user_openid, payload.content)
        delivery_mode = "active_fallback"
        reply_msg_id = ""
        msg_seq = None

    status_code = int(result.get("status_code") or 500)
    success = 200 <= status_code < 300
    response_data = result.get("data") if isinstance(result.get("data"), dict) else {}
    qq_message_id = str(response_data.get("id") or "") if isinstance(response_data, dict) else ""
    detail = "" if success else _error_detail(result)
    saved = chat_repository.record_outbound(
        bot_id=payload.bot_id,
        user_openid=payload.user_openid,
        content=payload.content,
        success=success,
        qq_message_id=qq_message_id,
        reply_to_msg_id=reply_msg_id,
        msg_seq=msg_seq,
        status_code=status_code,
        detail=detail,
        created_at=str(response_data.get("timestamp") or "") or None if isinstance(response_data, dict) else None,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"QQ 单聊消息发送失败：{detail}")
    return {"message": saved, "delivery_mode": delivery_mode}
