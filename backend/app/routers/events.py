import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.services.bot_repository import bot_repository
from app.services.chat_service import chat_service
from app.services.event_catalog import event_catalog_payload
from app.services.group_moderation_service import group_moderation_service
from app.services.group_verification_service import group_verification_service
from app.services.library_delivery_service import library_delivery_service
from app.services.qq_signature import sign_validation, verify_request_signature

router = APIRouter(prefix="/events", tags=["events"])
_recent_events: deque[dict[str, Any]] = deque(maxlen=100)
logger = logging.getLogger(__name__)


@router.get("/recent")
def recent_events(bot_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
    events = list(reversed(_recent_events))
    if bot_id:
        events = [event for event in events if event.get("bot_id") == bot_id]
    return events


@router.get("/status")
def event_status(bot_id: str = Query(...)) -> dict[str, Any]:
    bot = bot_repository.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")

    detection = bot_repository.get_event_detection(bot_id)
    verified_at, observed = detection if detection is not None else (None, {})
    selected = set(bot.event_scopes)
    groups = event_catalog_payload()
    selected_count = 0
    observed_count = 0

    for group in groups:
        for event in group["events"]:
            code = str(event["code"])
            event["selected"] = code in selected
            event["observed"] = code in observed
            event["last_received_at"] = observed.get(code)
            selected_count += int(event["selected"])
            observed_count += int(event["observed"])

    return {
        "bot_id": bot.id,
        "app_id": bot.app_id,
        "callback_url": bot.callback_url,
        "callback_verified": bool(verified_at),
        "callback_verified_at": verified_at,
        "official_subscription_query_supported": False,
        "detection_note": "QQ Webhook 已勾选事件没有公开查询接口；本页通过回调验证和真实事件到达记录接入状态。",
        "selected_count": selected_count,
        "observed_count": observed_count,
        "total_count": sum(len(group["events"]) for group in groups),
        "groups": groups,
    }


def _resolve_credentials(app_id: str | None) -> tuple[str, str, str] | None:
    """Resolve bot credentials for a webhook callback.

    When the callback path/header carries an explicit AppID, only that bot's
    secret may be used. Falling back to "the only configured bot" would sign
    validation challenges with the wrong key and QQ reports 签名校验不通过.
    The single-bot fallback remains only for the legacy `/callback` entry.
    """
    cleaned = str(app_id or "").strip()
    if cleaned:
        return bot_repository.get_credentials_by_app_id(cleaned)

    configured = [bot for bot in bot_repository.list() if bot.has_secret and bot.app_id]
    if len(configured) == 1:
        return bot_repository.get_credentials_by_app_id(configured[0].app_id)
    return None


async def _process_feature_event(bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
    handlers = (
        ("chat", chat_service.handle_event),
        ("group_verification", group_verification_service.handle_event),
        ("group_moderation", group_moderation_service.handle_event),
        ("library_delivery", library_delivery_service.handle_event),
    )
    for name, handler in handlers:
        try:
            await handler(bot_id, event_type, payload)
        except Exception:
            logger.exception("%s event processing failed: %s", name, event_type)


async def _receive_event(
    request: Request,
    app_id: str | None,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
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
    path_app_id = str(app_id or "").strip()
    requested_app_id = path_app_id or header_app_id
    credentials = _resolve_credentials(requested_app_id or None)
    if credentials is None:
        detail = (
            f"未找到 AppID {requested_app_id} 的机器人凭证；请先在管理台添加该机器人并填写正确 AppSecret"
            if requested_app_id
            else "未找到对应 AppID 的机器人凭证"
        )
        raise HTTPException(status_code=404, detail=detail)

    bot_id, resolved_app_id, secret = credentials
    op = payload.get("op")
    data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
    received_at = datetime.now(timezone.utc).isoformat()

    if op == 13:
        plain_token = str(data.get("plain_token") or "")
        event_ts = str(data.get("event_ts") or "")
        if not plain_token or not event_ts:
            raise HTTPException(status_code=400, detail="缺少 plain_token 或 event_ts")
        signature = sign_validation(secret, event_ts, plain_token)
        bot_repository.mark_callback_verified(bot_id, received_at)
        _recent_events.append({
            "id": str(uuid4()),
            "bot_id": bot_id,
            "app_id": resolved_app_id,
            "type": "CALLBACK_VALIDATION",
            "received_at": received_at,
            "payload": {"op": 13},
        })
        return JSONResponse({"plain_token": plain_token, "signature": signature})

    timestamp = request.headers.get("X-Signature-Timestamp") or request.headers.get("x-signature-timestamp") or ""
    signature_hex = request.headers.get("X-Signature-Ed25519") or request.headers.get("x-signature-ed25519") or ""
    if timestamp and signature_hex and not verify_request_signature(secret, timestamp, body, signature_hex):
        raise HTTPException(status_code=401, detail="签名校验失败")

    event_type = str(payload.get("t") or payload.get("type") or (f"OP_{op}" if op is not None else "UNKNOWN"))
    bot_repository.mark_event_observed(bot_id, event_type, received_at)
    _recent_events.append({
        "id": str(uuid4()),
        "bot_id": bot_id,
        "app_id": resolved_app_id,
        "type": event_type,
        "received_at": received_at,
        "payload": payload,
    })
    background_tasks.add_task(_process_feature_event, bot_id, event_type, payload)
    return JSONResponse({"op": 12})


@router.post("/callback/{app_id}")
async def receive_event_for_app(
    app_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Recommended multi-bot callback entry: one URL per AppID."""
    return await _receive_event(request, app_id.strip(), background_tasks)


@router.post("/callback")
async def receive_event_legacy(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Compatibility entry for a single configured bot or X-Bot-Appid header."""
    return await _receive_event(request, None, background_tasks)
