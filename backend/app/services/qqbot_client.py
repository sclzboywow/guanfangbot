import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.config import Settings, get_settings
from app.services.bot_repository import bot_repository


class QQBotClient:
    """Per-bot QQ OpenAPI client with server-side access-token caching."""

    def __init__(self, bot_id: str, app_id: str, client_secret: str, settings: Settings | None = None) -> None:
        self.bot_id = bot_id
        self.app_id = app_id
        self.client_secret = client_secret
        self.settings = settings or get_settings()
        self._token: str | None = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()
        self._fingerprint = f"{app_id}:{client_secret}"

    @property
    def token_cached(self) -> bool:
        return bool(self._token and time.time() < self._expires_at)

    def update_credentials(self, app_id: str, client_secret: str) -> None:
        fingerprint = f"{app_id}:{client_secret}"
        if fingerprint != self._fingerprint:
            self.app_id = app_id
            self.client_secret = client_secret
            self._fingerprint = fingerprint
            self._token = None
            self._expires_at = 0

    async def get_access_token(self, force: bool = False) -> tuple[str, int]:
        if not self.app_id or not self.client_secret:
            raise HTTPException(status_code=503, detail="该机器人尚未配置 AppID / AppSecret")

        if not force and self.token_cached:
            return self._token or "", max(0, int(self._expires_at - time.time()))

        async with self._lock:
            if not force and self.token_cached:
                return self._token or "", max(0, int(self._expires_at - time.time()))

            payload = {"appId": self.app_id, "clientSecret": self.client_secret}
            try:
                async with httpx.AsyncClient(timeout=self.settings.qqbot_request_timeout) as client:
                    response = await client.post(self.settings.qqbot_token_url, json=payload)
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:500]
                raise HTTPException(status_code=502, detail=f"QQ Token 接口返回错误：{detail}") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise HTTPException(status_code=502, detail=f"无法获取 QQ Access Token：{exc}") from exc

            token = data.get("access_token")
            if not token:
                raise HTTPException(status_code=502, detail=f"QQ Token 响应缺少 access_token：{data}")
            expires_in = int(data.get("expires_in", 7200))
            self._token = str(token)
            self._expires_at = time.time() + max(60, expires_in - 60)
            return self._token, expires_in

    async def _request_once(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None,
        body: Any | None,
        *,
        force_token: bool = False,
    ) -> dict[str, Any]:
        token, _ = await self.get_access_token(force=force_token)
        url = f"{self.settings.qqbot_api_base.rstrip('/')}{path}"
        headers = {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.qqbot_request_timeout) as client:
                response = await client.request(method, url, params=query, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"QQ OpenAPI 网络错误：{exc}") from exc

        try:
            data: Any = response.json()
        except ValueError:
            data = response.text

        safe_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() in {"content-type", "date", "x-request-id", "trace-id"}
        }
        return {"status_code": response.status_code, "data": data, "headers": safe_headers}

    async def request(self, method: str, path: str, query: dict[str, str] | None, body: Any | None) -> dict[str, Any]:
        result = await self._request_once(method, path, query, body)
        if result["status_code"] == 401:
            result = await self._request_once(method, path, query, body, force_token=True)
        return result

    async def send_group_text(
        self,
        group_openid: str,
        content: str,
        *,
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
        collapse_whitespace: bool = True,
    ) -> dict[str, Any]:
        """Send a plain-text group message. By default collapses to one line."""
        text = str(content).replace("\r\n", "\n").replace("\r", "\n")
        if collapse_whitespace:
            normalized = " ".join(text.split())
        else:
            normalized = "\n".join(line.rstrip() for line in text.split("\n")).strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="群消息内容不能为空")
        body: dict[str, Any] = {"content": normalized, "msg_type": 0}
        if msg_id:
            body["msg_id"] = msg_id
            body["msg_seq"] = msg_seq
        elif event_id:
            body["event_id"] = event_id
            body["msg_seq"] = msg_seq
        path = f"/v2/groups/{quote(group_openid, safe='')}/messages"
        return await self.request("POST", path, None, body)

    async def send_c2c_text(
        self,
        user_openid: str,
        content: str,
        *,
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
        is_wakeup: bool = False,
    ) -> dict[str, Any]:
        """Send a plain-text QQ single-chat message to a known user OpenID."""
        normalized = "\n".join(
            line.rstrip()
            for line in str(content).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ).strip()
        if not normalized:
            raise HTTPException(status_code=400, detail="单聊消息内容不能为空")
        body: dict[str, Any] = {"content": normalized, "msg_type": 0}
        if msg_id:
            body["msg_id"] = msg_id
            body["msg_seq"] = max(1, int(msg_seq))
        elif event_id:
            body["event_id"] = event_id
            body["msg_seq"] = max(1, int(msg_seq))
        elif is_wakeup:
            body["is_wakeup"] = True
        path = f"/v2/users/{quote(user_openid, safe='')}/messages"
        return await self.request("POST", path, None, body)

    async def retract_group_message(self, group_openid: str, message_id: str) -> dict[str, Any]:
        path = (
            f"/v2/groups/{quote(group_openid, safe='')}/messages/"
            f"{quote(message_id, safe='')}"
        )
        return await self.request("DELETE", path, None, None)

    async def fetch_me(self) -> dict[str, Any]:
        """Fetch current bot profile via GET /users/@me."""
        result = await self.request("GET", "/users/@me", None, None)
        if result["status_code"] >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"获取机器人资料失败：{result['data']}",
            )
        data = result["data"]
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="获取机器人资料失败：响应格式无效")
        return data


class QQBotClientManager:
    def __init__(self) -> None:
        self._clients: dict[str, QQBotClient] = {}
        self._lock = asyncio.Lock()

    async def get(self, bot_id: str) -> QQBotClient:
        credentials = bot_repository.get_credentials(bot_id)
        if credentials is None:
            bot = bot_repository.get(bot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="机器人不存在")
            raise HTTPException(status_code=503, detail="该机器人尚未配置完整凭证")

        app_id, client_secret = credentials
        async with self._lock:
            client = self._clients.get(bot_id)
            if client is None:
                client = QQBotClient(bot_id, app_id, client_secret)
                self._clients[bot_id] = client
            else:
                client.update_credentials(app_id, client_secret)
            return client

    def drop(self, bot_id: str) -> None:
        self._clients.pop(bot_id, None)


client_manager = QQBotClientManager()
