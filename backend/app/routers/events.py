import json
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.bot_repository import bot_repository
from app.services.qq_signature import sign_validation, verify_request_signature

router = APIRouter(prefix="/events", tags=["events"])
_recent_events: deque[dict[str, Any]] = deque(maxlen=50)


@router.get("/recent")
def recent_events() -> list[dict[str, Any]]:
    return list(reversed(_recent_events))


@router.post("/callback")
async def receive_event(request: Request) -> JSONResponse:
    """QQ Bot webhook receiver.

    Handles:
    - op=13 callback URL validation (Ed25519 sign event_ts + plain_token)
    - normal event dispatch ACK with op=12
    """
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效 JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="回调 body 必须是对象")

    app_id = (
        request.headers.get("X-Bot-Appid")
        or request.headers.get("x-bot-appid")
        or ""
    ).strip()
    credentials = bot_repository.get_credentials_by_app_id(app_id) if app_id else None

    # Fallback: if only one bot is configured, allow validation without matching header.
    if credentials is None:
        bots = bot_repository.list()
        configured = [bot for bot in bots if bot.has_secret and bot.app_id]
        if len(configured) == 1:
            credentials = bot_repository.get_credentials_by_app_id(configured[0].app_id)

    if credentials is None:
        raise HTTPException(status_code=404, detail="未找到对应 AppID 的机器人凭证，请先在管理台配置")

    bot_id, resolved_app_id, secret = credentials
    op = payload.get("op")
    data = payload.get("d") if isinstance(payload.get("d"), dict) else {}

    # Callback address validation
    if op == 13:
        plain_token = str(data.get("plain_token") or "")
        event_ts = str(data.get("event_ts") or "")
        if not plain_token or not event_ts:
            raise HTTPException(status_code=400, detail="缺少 plain_token 或 event_ts")
        signature = sign_validation(secret, event_ts, plain_token)
        # Callback URL verified by QQ platform => mark bot online
        bot_repository.set_status(bot_id, "online")
        _recent_events.append({
            "id": str(uuid4()),
            "type": "CALLBACK_VALIDATION",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"bot_id": bot_id, "app_id": resolved_app_id, "op": 13},
        })
        return JSONResponse({"plain_token": plain_token, "signature": signature})

    # Verify event signature for non-validation callbacks when headers present
    timestamp = request.headers.get("X-Signature-Timestamp") or request.headers.get("x-signature-timestamp") or ""
    signature_hex = request.headers.get("X-Signature-Ed25519") or request.headers.get("x-signature-ed25519") or ""
    if timestamp and signature_hex:
        if not verify_request_signature(secret, timestamp, body, signature_hex):
            raise HTTPException(status_code=401, detail="签名校验失败")

    event_type = str(payload.get("t") or payload.get("type") or f"OP_{op}" or "UNKNOWN")
    bot_repository.set_status(bot_id, "online")
    _recent_events.append({
        "id": str(uuid4()),
        "type": event_type,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    })
    # HTTP Callback ACK
    return JSONResponse({"op": 12})
