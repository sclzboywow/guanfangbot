from __future__ import annotations

import json
import secrets
import string
from typing import Any

import httpx

ALLOWED_PERIODS = {0, 1, 7, 30}
PASSWORD_ALPHABET = string.ascii_lowercase + string.digits
AUTH_ERROR_CODES = {110, 111}


def generate_share_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4))


def _share_link(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    text = text.removeprefix("/s/").removeprefix("s/")
    return f"https://pan.baidu.com/s/{text}"


def _is_auth_error(error_number: int, data: dict[str, Any]) -> bool:
    if error_number in AUTH_ERROR_CODES:
        return True
    error_name = str(data.get("error") or "").strip().lower()
    message = str(
        data.get("errmsg")
        or data.get("error_msg")
        or data.get("message")
        or ""
    ).lower()
    return error_name in {"invalid_token", "expired_token"} or "access token" in message


class BaiduPanShareClient:
    def __init__(self, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout = timeout
        self.transport = transport

    async def create_share(
        self,
        *,
        api_url: str,
        api_method: str,
        access_token: str,
        fsids: list[str],
        period: int,
        pwd: str | None = None,
    ) -> dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            return {"success": False, "status_code": None, "detail": "百度网盘尚未完成扫码授权", "auth_error": True}
        if int(period) not in ALLOWED_PERIODS:
            return {"success": False, "status_code": None, "detail": "分享有效期只支持 0、1、7、30 天", "auth_error": False}
        clean_fsids = [str(item).strip() for item in fsids if str(item).strip()]
        if not clean_fsids:
            return {"success": False, "status_code": None, "detail": "缺少可分享的 fsid", "auth_error": False}
        password = (pwd or generate_share_password()).strip().lower()
        if len(password) != 4 or any(ch not in PASSWORD_ALPHABET for ch in password):
            return {"success": False, "status_code": None, "detail": "分享码必须是 4 位小写字母或数字", "auth_error": False}

        params = {"method": str(api_method or "rapidshare").strip(), "access_token": token}
        form = {
            "fsid_list": json.dumps(clean_fsids, ensure_ascii=False, separators=(",", ":")),
            "period": str(int(period)),
            "pwd": password,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(str(api_url).strip(), params=params, data=form)
        except httpx.HTTPError as exc:
            return {
                "success": False,
                "status_code": None,
                "detail": f"百度网盘接口网络错误：{exc}",
                "auth_error": False,
            }

        try:
            data: Any = response.json()
        except ValueError:
            data = {"raw": response.text[:1000]}
        if not isinstance(data, dict):
            data = {"raw": data}
        error_code = data.get("errno", data.get("error_code", 0 if response.is_success else response.status_code))
        try:
            error_number = int(error_code)
        except (TypeError, ValueError):
            error_number = -1
        link = _share_link(data.get("link") or data.get("short_url"))
        success = response.is_success and error_number == 0 and bool(link)
        if success:
            try:
                response_period = int(data.get("period", period))
            except (TypeError, ValueError):
                response_period = int(period)
            return {
                "success": True,
                "status_code": response.status_code,
                "link": link,
                "short_url": str(data.get("short_url") or ""),
                "pwd": str(data.get("pwd") or password),
                "period": response_period,
                "detail": "",
                "auth_error": False,
            }
        message = data.get("errmsg") or data.get("error_msg") or data.get("message") or data.get("raw") or data
        return {
            "success": False,
            "status_code": response.status_code,
            "error_code": error_number,
            "detail": str(message)[:1500],
            "auth_error": _is_auth_error(error_number, data),
        }


baidu_pan_share_client = BaiduPanShareClient()
