import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx

from app.config import Settings
from app.services.baidu_oauth_repository import BaiduOAuthRepository
from app.services.baidu_oauth_service import BaiduOAuthService
from app.services.baidu_pan_client import BaiduPanShareClient, generate_share_password
from app.services.library_catalog import inspect_catalog, search_catalog
from app.services.library_delivery_repository import LibraryDeliveryRepository
from app.services.library_delivery_service import LibraryDeliveryService, extract_search_query


def create_catalog(path: Path, count: int = 7) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        'CREATE TABLE "新网盘资料" ("标题" TEXT, "分类" TEXT, "大小" INTEGER, "fsid" INTEGER, "网盘地址" TEXT)'
    )
    for index in range(count):
        connection.execute(
            'INSERT INTO "新网盘资料" VALUES (?, ?, ?, ?, ?)',
            (
                f"不动产资料{index + 1}",
                "地方标准",
                1000 + index,
                543379444407161 + index,
                f"/云栈/不动产资料{index + 1}",
            ),
        )
    connection.commit()
    connection.close()


def settings_for(path: Path) -> dict[str, object]:
    return {
        "database_path": str(path),
        "table_name": "新网盘资料",
        "title_column": "标题",
        "category_column": "分类",
        "size_column": "大小",
        "fsid_column": "fsid",
        "path_column": "网盘地址",
    }


def oauth_settings() -> Settings:
    return Settings(
        baidu_pan_app_key="app-key",
        baidu_pan_secret_key="secret-key",
        baidu_oauth_base="https://openapi.baidu.com",
        baidu_oauth_timeout=5,
    )


def test_catalog_reports_total_and_returns_first_five(tmp_path: Path) -> None:
    catalog = tmp_path / "标准库.sqlite3"
    create_catalog(catalog)
    inspected = inspect_catalog(settings_for(catalog))
    total, results = search_catalog(settings_for(catalog), "不动产", limit=5)
    assert inspected["row_count"] == 7
    assert total == 7
    assert len(results) == 5
    assert results[0]["fsid"].isdigit()


def test_search_query_removes_qq_mention_and_whitespace() -> None:
    assert extract_search_query("<@!123456>   不动产  技术规程\n") == "不动产 技术规程"
    assert extract_search_query("@机器人： 企业开办") == "企业开办"


def test_repository_sessions_are_scoped(tmp_path: Path) -> None:
    repository = LibraryDeliveryRepository(tmp_path / "state.db")
    session = repository.create_session(
        bot_id="bot-1", group_openid="group-a", member_openid="member-a",
        query="不动产", total_count=1,
        results=[{"title": "资料", "fsid": "123", "category": "", "size": "", "pan_path": "/资料"}],
        ttl_seconds=180,
    )
    active = repository.get_active_session("bot-1", "group-a", "member-a")
    assert active is not None and active["id"] == session["id"]
    assert repository.get_active_session("bot-1", "group-b", "member-a") is None
    assert repository.consume_session(session["id"]) is True
    assert repository.consume_session(session["id"]) is False


def test_share_password_format() -> None:
    password = generate_share_password()
    assert len(password) == 4
    assert password.isalnum()
    assert password == password.lower()


def test_baidu_share_client_sends_strict_fsid_json() -> None:
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = dict(request.url.params)
        captured["form"] = parse_qs((await request.aread()).decode())
        return httpx.Response(200, json={
            "errno": 0,
            "link": "https://pan.baidu.com/s/1example",
            "pwd": "a1b2",
            "period": 7,
        })

    client = BaiduPanShareClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.create_share(
        api_url="https://pan.baidu.com/rest/2.0/xpan/share",
        api_method="rapidshare",
        access_token="token",
        fsids=["543379444407161"],
        period=7,
        pwd="a1b2",
    ))
    assert result["success"] is True
    assert captured["query"]["method"] == "rapidshare"
    assert json.loads(captured["form"]["fsid_list"][0]) == ["543379444407161"]


def test_device_code_oauth_saves_tokens_without_exposing_them(tmp_path: Path) -> None:
    repository = BaiduOAuthRepository(tmp_path / "oauth.db")
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/oauth/2.0/device/code":
            return httpx.Response(200, json={
                "device_code": "device-code",
                "user_code": "ABCD-EFGH",
                "verification_url": "https://openapi.baidu.com/device",
                "qrcode_url": "https://openapi.baidu.com/oauth/2.0/qrcode/test",
                "expires_in": 300,
                "interval": 3,
            })
        if request.url.path == "/oauth/2.0/token":
            assert request.url.params["grant_type"] == "device_token"
            assert request.url.params["client_id"] == "app-key"
            assert request.url.params["client_secret"] == "secret-key"
            return httpx.Response(200, json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 2592000,
                "scope": "basic netdisk",
            })
        return httpx.Response(404)

    service = BaiduOAuthService(
        repository=repository,
        settings=oauth_settings(),
        transport=httpx.MockTransport(handler),
    )

    async def run_flow() -> tuple[dict, dict]:
        session = await service.start_authorization("bot-1")
        with sqlite3.connect(repository.path) as connection:
            connection.execute(
                "UPDATE baidu_oauth_sessions SET next_poll_at = ? WHERE id = ?",
                ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session["session_id"]),
            )
        polled = await service.poll_authorization(session["session_id"])
        return session, polled

    session, polled = asyncio.run(run_flow())
    assert session["qr_image_url"].startswith("/api/library-delivery/oauth/qr/")
    assert polled["authorized"] is True
    private = repository.get_tokens()
    assert private["access_token"] == "access-secret"
    assert private["refresh_token"] == "refresh-secret"
    public = service.public_status()
    assert public["authorized"] is True
    assert "access_token" not in public
    assert "refresh_token" not in public
    assert calls == ["/oauth/2.0/device/code", "/oauth/2.0/token"]


def test_oauth_refreshes_expired_access_token(tmp_path: Path) -> None:
    repository = BaiduOAuthRepository(tmp_path / "oauth.db")
    repository.save_tokens(
        access_token="old-access",
        refresh_token="refresh-secret",
        expires_in=60,
        scope="basic netdisk",
    )
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE baidu_oauth_tokens SET expires_at = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
        )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/2.0/token"
        assert request.url.params["grant_type"] == "refresh_token"
        assert request.url.params["refresh_token"] == "refresh-secret"
        return httpx.Response(200, json={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 2592000,
            "scope": "basic netdisk",
        })

    service = BaiduOAuthService(
        repository=repository,
        settings=oauth_settings(),
        transport=httpx.MockTransport(handler),
    )
    token = asyncio.run(service.get_access_token())
    assert token == "new-access"
    assert repository.get_tokens()["refresh_token"] == "new-refresh"


class FakeQQClient:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_group_text(self, group_openid: str, content: str, **kwargs):
        self.messages.append(content)
        return {"status_code": 200, "data": {"id": f"sent-{len(self.messages)}"}}


class FakeShareClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_share(self, **kwargs):
        self.calls += 1
        return {
            "success": True,
            "status_code": 200,
            "link": "https://pan.baidu.com/s/1example",
            "pwd": "a1b2",
            "period": 7,
            "auth_error": False,
        }


class FakeOAuthService:
    async def get_access_token(self, force_refresh: bool = False) -> str:
        return "backend-managed-token"


def test_search_then_plain_number_creates_one_share(tmp_path: Path) -> None:
    catalog = tmp_path / "标准库.sqlite3"
    create_catalog(catalog, count=6)
    repository = LibraryDeliveryRepository(tmp_path / "state.db")
    repository.update_settings(
        "bot-test", enabled=True,
        database_path=str(catalog), table_name="新网盘资料",
        title_column="标题", category_column="分类", size_column="大小",
        fsid_column="fsid", path_column="网盘地址", share_period=7,
        session_ttl_seconds=180,
    )
    qq = FakeQQClient()
    share = FakeShareClient()

    async def qq_provider(bot_id: str):
        return qq

    service = LibraryDeliveryService(repository, share, qq_provider, FakeOAuthService())  # type: ignore[arg-type]
    search_payload = {
        "id": "event-search",
        "d": {
            "id": "message-search", "group_openid": "group-1",
            "author": {"member_openid": "member-1"},
            "content": "<@!bot> 不动产",
        },
    }
    selection_payload = {
        "d": {
            "id": "message-selection", "group_openid": "group-1",
            "author": {"member_openid": "member-1"}, "content": "1",
        }
    }

    async def run_flow() -> None:
        await service.handle_event("bot-test", "GROUP_AT_MESSAGE_CREATE", search_payload)
        await service.handle_event("bot-test", "GROUP_MESSAGE_CREATE", selection_payload)
        await service.handle_event("bot-test", "GROUP_MESSAGE_CREATE", selection_payload)

    asyncio.run(run_flow())
    assert "找到6个结果" in qq.messages[0]
    assert "\n" not in qq.messages[0]
    assert share.calls == 1
    assert "分享链接：https://pan.baidu.com/s/1example" in qq.messages[-1]
    assert "\n" not in qq.messages[-1]
