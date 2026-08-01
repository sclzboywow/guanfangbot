import json
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.services.bot_repository import bot_repository
from app.services.qq_signature import sign_validation, verify_request_signature

router = APIRouter(prefix="/events", tags=["events"])
_recent_events: deque[dict[str, Any]] = deque(maxlen=100)


@router.get("/recent")
def recent_events(bot_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
    events = list(reversed(_recent_events))
    if bot_id:
        events = [event for event in events if event.get("bot_id") == bot_id]
    return events


def _resolve_credentials(app_id: str | None) -> tuple[str, str, str] | None:
    if app_id:
        credentials = bot_repository.get_credentials_by_app_id(app_id)
        if credentials is not None:
            return credentials

    configured = [bot for bot in bot_repository.list() if bot.has_secret and bot.app_id]
    if len(configured) == 1:
        return bot_repository.get_credentials_by_app_id(configured[0].app_id)
    return None


async def _receive_event(request: Request, app_id: str | None) -> JSONResponse:
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效 JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="回调 body 必须是对象")

    header_app_id = (
        request.headers.get("X-Bot-Appid")
        or request.headers.get("x-bot-appid")
        or ""
    ).strip()
    credentials = _resolve_credentials(app_id or header_app_id)
    if credentials is None:
        raise HTTPException(status_code=404, detail="未找到对应 AppID 的机器人凭证")

    bot_id, resolved_app_id, secret = credentials
    op = payload.get("op")
    data = payload.get("d") if isinstance(payload.get("d"), dict) else {}

    if op == 13:
        plain_token = str(data.get("plain_token") or "")
        event_ts = str(data.get("event_ts") or "")
        if not plain_token or not event_ts:
            raise HTTPException(status_code=400, detail="缺少 plain_token 或 event_ts")
        signature = sign_validation(secret, event_ts, plain_token)
        bot_repository.set_status(bot_id, "online")
        _recent_events.append({
            "id": str(uuid4()),
            "bot_id": bot_id,
            "app_id": resolved_app_id,
            "type": "CALLBACK_VALIDATION",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"op": 13},
        })
        return JSONResponse({"plain_token": plain_token, "signature": signature})

    timestamp = request.headers.get("X-Signature-Timestamp") or request.headers.get("x-signature-timestamp") or ""
    signature_hex = request.headers.get("X-Signature-Ed25519") or request.headers.get("x-signature-ed25519") or ""
    if timestamp and signature_hex and not verify_request_signature(secret, timestamp, body, signature_hex):
        raise HTTPException(status_code=401, detail="签名校验失败")

    event_type = str(payload.get("t") or payload.get("type") or (f"OP_{op}" if op is not None else "UNKNOWN"))
    bot_repository.set_status(bot_id, "online")
    _recent_events.append({
        "id": str(uuid4()),
        "bot_id": bot_id,
        "app_id": resolved_app_id,
        "type": event_type,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    })
    return JSONResponse({"op": 12})


@router.post("/callback/{app_id}")
async def receive_event_for_app(app_id: str, request: Request) -> JSONResponse:
    """Recommended multi-bot callback entry: one URL per AppID."""
    return await _receive_event(request, app_id.strip())


@router.post("/callback")
async def receive_event_legacy(request: Request) -> JSONResponse:
    """Compatibility entry for a single configured bot or X-Bot-Appid header."""
    return await _receive_event(request, None)
