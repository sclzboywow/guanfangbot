from __future__ import annotations

import json
import secrets
import string
from typing import Any

import httpx

ALLOWED_PERIODS = {0, 1, 7, 30}
PASSWORD_ALPHABET = string.ascii_lowercase + string.digits
AUTH_ERROR_CODES = {110, 111}
# 开放平台实际可用的创建分享方法；历史配置里的 rapidshare 会映射到 set。
SHARE_METHOD_ALIASES = {
    "rapidshare": "set",
    "share": "set",
    "create": "set",
}


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
        or data.get("show_msg")
        or ""
    ).lower()
    return error_name in {"invalid_token", "expired_token"} or "access token" in message


def _normalize_share_method(api_method: str) -> str:
    method = str(api_method or "set").strip() or "set"
    return SHARE_METHOD_ALIASES.get(method.lower(), method)


def _to_fsid_ints(fsids: list[str]) -> list[int] | None:
    values: list[int] = []
    for item in fsids:
        text = str(item).strip()
        if not text.isdigit():
            return None
        values.append(int(text))
    return values


class BaiduPanShareClient:
    def __init__(self, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.timeout = timeout
        self.transport = transport

    async def fsid_exists(self, *, access_token: str, fsid: str) -> bool:
        token = str(access_token or "").strip()
        fsid_text = str(fsid or "").strip()
        if not token or not fsid_text.isdigit():
            return False
        params = {
            "method": "filemetas",
            "access_token": token,
            "fsids": json.dumps([int(fsid_text)], separators=(",", ":")),
            "dlink": "0",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get("https://pan.baidu.com/rest/2.0/xpan/multimedia", params=params)
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return False
        if not isinstance(data, dict):
            return False
        try:
            errno = int(data.get("errno", -1))
        except (TypeError, ValueError):
            return False
        return errno == 0 and bool(data.get("list"))

    async def resolve_fsid_by_path(self, *, access_token: str, pan_path: str) -> str | None:
        """Resolve the current fs_id for a Netdisk path when catalog fsids are stale."""
        token = str(access_token or "").strip()
        path = str(pan_path or "").strip()
        if not token or not path:
            return None
        if not path.startswith("/"):
            path = f"/{path}"
        parent, _, filename = path.rpartition("/")
        parent = parent or "/"
        if not filename:
            return None
        params = {
            "method": "list",
            "access_token": token,
            "dir": parent,
            "limit": "1000",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get("https://pan.baidu.com/rest/2.0/xpan/file", params=params)
                data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            errno = int(data.get("errno", -1))
        except (TypeError, ValueError):
            return None
        if errno != 0:
            return None
        for item in data.get("list") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("server_filename") or "") == filename or str(item.get("path") or "") == path:
                fsid = str(item.get("fs_id") or "").strip()
                if fsid.isdigit():
                    return fsid
        return None

    async def create_share(
        self,
        *,
        api_url: str,
        api_method: str,
        access_token: str,
        fsids: list[str],
        period: int,
        pwd: str | None = None,
        pan_path: str | None = None,
    ) -> dict[str, Any]:
        token = str(access_token or "").strip()
        if not token:
            return {"success": False, "status_code": None, "detail": "百度网盘尚未完成扫码授权", "auth_error": True}
        if int(period) not in ALLOWED_PERIODS:
            return {"success": False, "status_code": None, "detail": "分享有效期只支持 0、1、7、30 天", "auth_error": False}
        clean_fsids = [str(item).strip() for item in fsids if str(item).strip()]
        if not clean_fsids and not pan_path:
            return {"success": False, "status_code": None, "detail": "缺少可分享的 fsid", "auth_error": False}
        password = (pwd or generate_share_password()).strip().lower()
        if len(password) != 4 or any(ch not in PASSWORD_ALPHABET for ch in password):
            return {"success": False, "status_code": None, "detail": "分享码必须是 4 位小写字母或数字", "auth_error": False}

        candidates: list[str] = []
        for item in clean_fsids:
            if item not in candidates:
                candidates.append(item)
        if pan_path:
            resolved = await self.resolve_fsid_by_path(access_token=token, pan_path=pan_path)
            if resolved and resolved not in candidates:
                # Prefer live fsid from path when catalog ids may be stale.
                candidates.insert(0, resolved)

        last_failure: dict[str, Any] = {
            "success": False,
            "status_code": None,
            "detail": "缺少可分享的 fsid",
            "auth_error": False,
        }
        for fsid in candidates:
            result = await self._create_share_once(
                api_url=api_url,
                api_method=api_method,
                access_token=token,
                fsid=fsid,
                period=period,
                password=password,
            )
            if result.get("success"):
                return result
            last_failure = result
            # Retry next candidate only for missing/moved files.
            if int(result.get("error_code") or 0) not in {-3, 2, 12}:
                return result
        return last_failure

    async def _create_share_once(
        self,
        *,
        api_url: str,
        api_method: str,
        access_token: str,
        fsid: str,
        period: int,
        password: str,
    ) -> dict[str, Any]:
        fsid_ints = _to_fsid_ints([fsid])
        if not fsid_ints:
            return {"success": False, "status_code": None, "detail": f"无效 fsid：{fsid}", "auth_error": False}

        method = _normalize_share_method(api_method)
        params = {"method": method, "access_token": access_token}
        form = {
            "fid_list": json.dumps(fsid_ints, ensure_ascii=False, separators=(",", ":")),
            "period": str(int(period)),
            "pwd": password,
            "channel_list": "[]",
            "schannel": "4",
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
        link = _share_link(data.get("link") or data.get("shorturl") or data.get("short_url"))
        success = response.is_success and error_number == 0 and bool(link)
        if success:
            try:
                response_period = int(data.get("period", data.get("expiredType", period)))
            except (TypeError, ValueError):
                response_period = int(period)
            return {
                "success": True,
                "status_code": response.status_code,
                "link": link,
                "short_url": str(data.get("shorturl") or data.get("short_url") or ""),
                "pwd": str(data.get("pwd") or password),
                "period": response_period,
                "fsid": str(fsid_ints[0]),
                "detail": "",
                "auth_error": False,
            }
        message = (
            data.get("show_msg")
            or data.get("errmsg")
            or data.get("error_msg")
            or data.get("message")
            or data.get("raw")
            or data
        )
        detail = str(message).strip() or f"百度分享失败（errno={error_number}）"
        if response.status_code == 404:
            detail = f"分享接口不存在或方法无效（method={method}）"
        return {
            "success": False,
            "status_code": response.status_code,
            "error_code": error_number,
            "detail": detail[:1500],
            "auth_error": _is_auth_error(error_number, data),
        }


baidu_pan_share_client = BaiduPanShareClient()
