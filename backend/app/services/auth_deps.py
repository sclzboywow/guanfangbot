from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, Response

from app.config import get_settings
from app.services.auth_repository import auth_repository
from app.services.bot_repository import bot_repository

COOKIE_NAME = "qqbot_session"
AuthUser = dict[str, Any]


class RateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        bucket.append(now)


auth_rate_limiter = RateLimiter(limit=20, window_seconds=15 * 60)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def set_session_cookie(response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def public_user(user: AuthUser) -> dict[str, Any]:
    return {
        "id": str(user["id"]),
        "email": str(user["email"]),
        "role": str(user.get("role") or "user"),
        "created_at": str(user.get("created_at") or ""),
    }


def get_optional_user(request: Request) -> AuthUser | None:
    session_id = request.cookies.get(COOKIE_NAME, "")
    if not session_id:
        return None
    return auth_repository.get_user_by_session(session_id)


def require_user(request: Request) -> AuthUser:
    user = get_optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_owned_bot(bot_id: str, user: AuthUser) -> Any:
    bot = bot_repository.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    owner_id = bot_repository.get_owner_user_id(bot_id)
    if str(user.get("role") or "") != "admin" and owner_id != str(user["id"]):
        raise HTTPException(status_code=404, detail="机器人不存在")
    return bot


def owned_bot_dependency(bot_id_param: str = "bot_id") -> Callable[..., Any]:
    def dependency(request: Request, user: AuthUser = Depends(require_user)) -> Any:
        bot_id = request.path_params.get(bot_id_param) or request.query_params.get(bot_id_param)
        if not bot_id:
            raise HTTPException(status_code=422, detail="缺少 bot_id")
        return require_owned_bot(str(bot_id), user)

    return dependency
