from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.config import Settings, get_settings
from app.services.baidu_oauth_repository import (
    BaiduOAuthRepository,
    baidu_oauth_repository,
    parse_time,
    utc_now_dt,
)

PENDING_ERRORS = {"authorization_pending", "authorization_waiting"}
DENIED_ERRORS = {"authorization_declined", "access_denied"}
EXPIRED_ERRORS = {"expired_token", "invalid_grant", "invalid_device_code"}


class BaiduOAuthError(RuntimeError):
    pass


def _error_detail(data: dict[str, Any], fallback: str = "百度 OAuth 请求失败") -> str:
    value = (
        data.get("error_description")
        or data.get("errmsg")
        or data.get("error_msg")
        or data.get("message")
        or data.get("error")
        or fallback
    )
    return str(value)[:1200]


def _allowed_baidu_host(hostname: str | None) -> bool:
    host = str(hostname or "").lower().rstrip(".")
    return host == "baidu.com" or host.endswith(".baidu.com") or host == "bdstatic.com" or host.endswith(".bdstatic.com")


class BaiduOAuthService:
    """Owns server-side Baidu Netdisk authorization tokens per owner user."""

    def __init__(
        self,
        repository: BaiduOAuthRepository = baidu_oauth_repository,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings or get_settings()
        self.transport = transport
        self._refresh_lock = asyncio.Lock()

    @property
    def app_configured(self) -> bool:
        return bool(self.settings.baidu_pan_app_key.strip() and self.settings.baidu_pan_secret_key.strip())

    def _require_app(self) -> tuple[str, str]:
        app_key = self.settings.baidu_pan_app_key.strip()
        secret_key = self.settings.baidu_pan_secret_key.strip()
        if not app_key or not secret_key:
            raise BaiduOAuthError("服务器尚未配置 BAIDU_PAN_APP_KEY 和 BAIDU_PAN_SECRET_KEY")
        return app_key, secret_key

    async def _oauth_get(self, path: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
        url = f"{self.settings.baidu_oauth_base.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.baidu_oauth_timeout,
                transport=self.transport,
                follow_redirects=True,
                headers={"User-Agent": "QQBot-Shared-Library/1.0"},
            ) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise BaiduOAuthError(f"百度 OAuth 网络错误：{exc}") from exc
        try:
            data: Any = response.json()
        except ValueError:
            data = {"raw": response.text[:1200]}
        if not isinstance(data, dict):
            data = {"raw": data}
        return response.status_code, data

    def public_status(self, owner_user_id: str) -> dict[str, Any]:
        tokens = self.repository.get_tokens(owner_user_id)
        access_token = str(tokens.get("access_token") or "")
        refresh_token = str(tokens.get("refresh_token") or "")
        expires_at = parse_time(tokens.get("expires_at"))
        access_valid = bool(access_token and (expires_at is None or expires_at > utc_now_dt()))
        pending = self.repository.latest_pending_session(owner_user_id)
        return {
            "app_configured": self.app_configured,
            "authorized": bool(access_valid or refresh_token),
            "refreshable": bool(refresh_token),
            "token_expires_at": tokens.get("expires_at"),
            "authorized_at": tokens.get("authorized_at"),
            "scope": str(tokens.get("scope") or ""),
            "pending_session": self._public_session(pending) if pending else None,
        }

    @staticmethod
    def _public_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
        if session is None:
            return None
        session_id = str(session["id"])
        return {
            "session_id": session_id,
            "status": str(session.get("status") or "pending"),
            "user_code": str(session.get("user_code") or ""),
            "verification_url": str(session.get("verification_url") or ""),
            "qr_image_url": f"/api/library-delivery/oauth/qr/{session_id}",
            "expires_at": str(session.get("expires_at") or ""),
            "interval_seconds": max(3, int(session.get("interval_seconds") or 5)),
            "last_error": str(session.get("last_error") or ""),
        }

    async def start_authorization(self, requested_by_bot_id: str, owner_user_id: str) -> dict[str, Any]:
        app_key, _ = self._require_app()
        status_code, data = await self._oauth_get(
            "/oauth/2.0/device/code",
            {"response_type": "device_code", "client_id": app_key, "scope": "basic,netdisk"},
        )
        device_code = str(data.get("device_code") or "").strip()
        if status_code >= 400 or not device_code:
            raise BaiduOAuthError(_error_detail(data, "无法获取百度网盘授权二维码"))
        session = self.repository.create_session(
            requested_by_bot_id=requested_by_bot_id,
            owner_user_id=owner_user_id,
            device_code=device_code,
            user_code=str(data.get("user_code") or ""),
            verification_url=str(data.get("verification_url") or ""),
            qrcode_url=str(data.get("qrcode_url") or ""),
            expires_in=int(data.get("expires_in") or 300),
            interval_seconds=int(data.get("interval") or 5),
        )
        public = self._public_session(session)
        if public is None:
            raise BaiduOAuthError("无法创建百度网盘授权会话")
        return public

    async def poll_authorization(self, session_id: str) -> dict[str, Any]:
        app_key, secret_key = self._require_app()
        session = self.repository.get_session(session_id)
        if session is None:
            raise BaiduOAuthError("授权会话不存在")
        status = str(session.get("status") or "")
        if status != "pending":
            public = self._public_session(session)
            if public is None:
                raise BaiduOAuthError("授权会话不存在")
            public["authorized"] = status == "authorized"
            return public
        expires_at = parse_time(session.get("expires_at"))
        if expires_at is not None and expires_at <= utc_now_dt():
            self.repository.set_session_status(session_id, "expired", "二维码已过期")
            public = self._public_session(self.repository.get_session(session_id))
            if public is None:
                raise BaiduOAuthError("授权会话不存在")
            public["authorized"] = False
            return public
        if not self.repository.claim_poll(session_id):
            public = self._public_session(session)
            if public is None:
                raise BaiduOAuthError("授权会话不存在")
            public["authorized"] = False
            return public

        status_code, data = await self._oauth_get(
            "/oauth/2.0/token",
            {
                "grant_type": "device_token",
                "code": str(session.get("device_code") or ""),
                "client_id": app_key,
                "client_secret": secret_key,
            },
        )
        access_token = str(data.get("access_token") or "").strip()
        if access_token:
            owner_user_id = str(session.get("owner_user_id") or "").strip()
            if not owner_user_id:
                raise BaiduOAuthError("授权会话缺少归属用户")
            self.repository.save_tokens(
                owner_user_id,
                access_token=access_token,
                refresh_token=str(data.get("refresh_token") or ""),
                expires_in=int(data.get("expires_in") or 2592000),
                scope=str(data.get("scope") or ""),
            )
            self.repository.set_session_status(session_id, "authorized")
            public = self._public_session(self.repository.get_session(session_id))
            if public is None:
                raise BaiduOAuthError("授权会话不存在")
            public["authorized"] = True
            return public

        error_name = str(data.get("error") or "").strip().lower()
        try:
            errno = int(data.get("errno"))
        except (TypeError, ValueError):
            errno = None
        detail = _error_detail(data, f"百度 OAuth 返回 HTTP {status_code}")
        if error_name in PENDING_ERRORS or errno == -1:
            public = self._public_session(self.repository.get_session(session_id))
            if public is None:
                raise BaiduOAuthError("授权会话不存在")
            public["authorized"] = False
            return public
        if error_name == "slow_down":
            self.repository.delay_poll(session_id, 5)
            public = self._public_session(self.repository.get_session(session_id))
            if public is None:
                raise BaiduOAuthError("授权会话不存在")
            public["authorized"] = False
            return public
        if error_name in DENIED_ERRORS:
            self.repository.set_session_status(session_id, "denied", detail)
        elif error_name in EXPIRED_ERRORS:
            self.repository.set_session_status(session_id, "expired", detail)
        else:
            self.repository.set_session_status(session_id, "failed", detail)
        public = self._public_session(self.repository.get_session(session_id))
        if public is None:
            raise BaiduOAuthError("授权会话不存在")
        public["authorized"] = False
        return public

    async def _refresh_access_token(self, owner_user_id: str) -> str:
        app_key, secret_key = self._require_app()
        tokens = self.repository.get_tokens(owner_user_id)
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        if not refresh_token:
            raise BaiduOAuthError("百度网盘授权不可刷新，请重新扫码授权")
        status_code, data = await self._oauth_get(
            "/oauth/2.0/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_key,
                "client_secret": secret_key,
            },
        )
        access_token = str(data.get("access_token") or "").strip()
        if status_code >= 400 or not access_token:
            raise BaiduOAuthError(_error_detail(data, "刷新百度网盘授权失败，请重新扫码授权"))
        self.repository.save_tokens(
            owner_user_id,
            access_token=access_token,
            refresh_token=str(data.get("refresh_token") or refresh_token),
            expires_in=int(data.get("expires_in") or 2592000),
            scope=str(data.get("scope") or tokens.get("scope") or ""),
        )
        return access_token

    async def get_access_token(self, owner_user_id: str, force_refresh: bool = False) -> str:
        tokens = self.repository.get_tokens(owner_user_id)
        token = str(tokens.get("access_token") or "").strip()
        expires_at = parse_time(tokens.get("expires_at"))
        now = utc_now_dt()
        if not force_refresh and token and (expires_at is None or expires_at > now + timedelta(minutes=5)):
            return token
        async with self._refresh_lock:
            tokens = self.repository.get_tokens(owner_user_id)
            token = str(tokens.get("access_token") or "").strip()
            expires_at = parse_time(tokens.get("expires_at"))
            now = utc_now_dt()
            if not force_refresh and token and (expires_at is None or expires_at > now + timedelta(minutes=5)):
                return token
            if not token and not str(tokens.get("refresh_token") or "").strip():
                raise BaiduOAuthError("百度网盘尚未扫码授权")
            return await self._refresh_access_token(owner_user_id)

    async def fetch_qr_image(self, session_id: str) -> tuple[bytes, str]:
        session = self.repository.get_session(session_id)
        if session is None or str(session.get("status")) != "pending":
            raise BaiduOAuthError("授权二维码不存在或已失效")
        expires_at = parse_time(session.get("expires_at"))
        if expires_at is not None and expires_at <= utc_now_dt():
            raise BaiduOAuthError("授权二维码已过期")
        current_url = str(session.get("qrcode_url") or "").strip()
        parsed = urlparse(current_url)
        if parsed.scheme not in {"http", "https"} or not _allowed_baidu_host(parsed.hostname):
            raise BaiduOAuthError("百度返回的二维码地址无效")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.baidu_oauth_timeout,
                transport=self.transport,
                follow_redirects=False,
                headers={"User-Agent": "QQBot-Shared-Library/1.0"},
            ) as client:
                response: httpx.Response | None = None
                for _ in range(4):
                    response = await client.get(current_url)
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    location = response.headers.get("location", "")
                    next_url = urljoin(current_url, location)
                    next_parsed = urlparse(next_url)
                    if next_parsed.scheme not in {"http", "https"} or not _allowed_baidu_host(next_parsed.hostname):
                        raise BaiduOAuthError("百度二维码跳转到了不允许的地址")
                    current_url = next_url
                if response is None:
                    raise BaiduOAuthError("无法读取百度授权二维码")
                response.raise_for_status()
        except BaiduOAuthError:
            raise
        except httpx.HTTPError as exc:
            raise BaiduOAuthError(f"读取百度授权二维码失败：{exc}") from exc
        content_type = response.headers.get("content-type", "image/png").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise BaiduOAuthError("百度二维码响应不是图片")
        return response.content, content_type


baidu_oauth_service = BaiduOAuthService()
