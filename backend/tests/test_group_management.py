import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.group_management_repository import GroupManagementRepository
from app.services.group_management_service import GroupManagementService


class FakeClient:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[tuple[str, str, dict | None, object]] = []

    async def request(self, method: str, path: str, query, body):
        self.requests.append((method, path, query, body))
        if self.responses:
            return self.responses.pop(0)
        return {"status_code": 200, "data": {}}


def service_with_client(path: Path, client: FakeClient) -> tuple[GroupManagementService, GroupManagementRepository]:
    repository = GroupManagementRepository(path)

    async def provider(_bot_id: str):
        return client

    return GroupManagementService(repository, provider), repository


def test_join_request_event_is_persisted_and_group_is_remembered(tmp_path: Path) -> None:
    service, repository = service_with_client(tmp_path / "management.db", FakeClient())
    payload = {
        "d": {
            "group_openid": "group-1",
            "join_request_id": "request-1",
            "member_openid": "member-1",
            "username": "申请人",
            "risk_tips": "",
            "apply_at": "2026-08-10T10:00:00+08:00",
            "apply_source": "self_apply",
            "verify_info": {"method": "verify_message", "verify_message": "答案"},
        }
    }

    asyncio.run(service.handle_event("bot-1", "GROUP_JOIN_REQUEST", payload))

    requests = repository.list_join_requests("bot-1")
    assert len(requests) == 1
    assert requests[0]["status"] == "pending"
    assert requests[0]["verify_info"]["verify_message"] == "答案"
    assert repository.list_groups("bot-1")[0]["group_openid"] == "group-1"


def test_auto_approved_event_is_not_left_pending(tmp_path: Path) -> None:
    service, repository = service_with_client(tmp_path / "management.db", FakeClient())
    asyncio.run(service.handle_event("bot-1", "GROUP_JOIN_REQUEST", {
        "d": {
            "group_openid": "group-1",
            "join_request_id": "request-auto",
            "member_openid": "member-1",
            "auto_approved": {"strategy_id": "st-1"},
        }
    }))
    request = repository.list_join_requests("bot-1")[0]
    assert request["status"] == "auto_approved"
    assert request["auto_strategy_id"] == "st-1"


def test_sync_uses_query_pagination_and_records_requests(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 200, "data": {"list": [{
            "join_request_id": "request-1", "member_openid": "member-1", "username": "用户"
        }], "next_cursor": "next"}},
        {"status_code": 200, "data": {"list": [], "next_cursor": ""}},
    ])
    service, repository = service_with_client(tmp_path / "management.db", client)
    result = asyncio.run(service.sync_join_requests("bot-1", "group-1"))
    assert result == {"synced": 1, "pages": 2, "truncated": False}
    assert client.requests[0][2] == {"limit": "100"}
    assert client.requests[1][2] == {"limit": "100", "cursor": "next"}
    assert repository.list_join_requests("bot-1")[0]["group_openid"] == "group-1"


def test_decision_uses_all_official_options(tmp_path: Path) -> None:
    client = FakeClient()
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.upsert_join_request("bot-1", {
        "group_openid": "group-1", "join_request_id": "request-1", "member_openid": "member-1"
    }, source="test")

    asyncio.run(service.decide_join_request(
        "bot-1",
        group_openid="group-1",
        member_openid="member-1",
        join_request_id="request-1",
        op="decline",
        reject_reason="不符合要求",
        add_to_member_blacklist=True,
    ))

    method, path, _, body = client.requests[0]
    assert method == "POST"
    assert path.endswith("/approval_join_request/member-1")
    assert body == {
        "op": "decline",
        "join_request_id": "request-1",
        "reject_reason": "不符合要求",
        "add_to_member_blacklist": True,
    }
    assert repository.list_join_requests("bot-1")[0]["status"] == "declined"


def test_batch_mute_uses_one_official_request_then_refreshes(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 200, "data": {}},
        {"status_code": 200, "data": {"global_rule": {"mode": "none"}, "members": []}},
    ])
    service, _ = service_with_client(tmp_path / "management.db", client)
    members = [
        {"op": "add", "member_openid": "member-1", "mute_expire_at": "2026-08-11T00:00:00Z"},
        {"op": "update", "member_openid": "member-2", "mute_expire_at": "2026-08-12T00:00:00Z"},
    ]

    result = asyncio.run(service.set_member_mutes("bot-1", "group-1", members))

    assert result["global_rule"]["mode"] == "none"
    assert client.requests[0] == (
        "POST",
        "/v2/groups/group-1/restrict_chat_setting",
        None,
        {"members": members},
    )
    assert client.requests[1][0:3] == (
        "GET",
        "/v2/groups/group-1/restrict_chat_setting",
        None,
    )


def test_create_strategy_supports_group_numbers_and_openids(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 200, "data": {"strategy_id": "number-strategy"}},
        {"status_code": 200, "data": {"strategy_id": "openid-strategy"}},
    ])
    service, _ = service_with_client(tmp_path / "management.db", client)

    asyncio.run(service.create_strategy(
        "bot-1", group_mode="group_ids", groups=["123456", "789012"],
        is_enable="on", expire_at=None, remark="群号模式",
    ))
    asyncio.run(service.create_strategy(
        "bot-1", group_mode="group_openids", groups=["group-a"],
        is_enable="off", expire_at=None, remark="OpenID模式",
    ))

    assert client.requests[0][3]["group_ids"] == [123456, 789012]
    assert "group_openids" not in client.requests[0][3]
    assert client.requests[1][3]["group_openids"] == ["group-a"]
    assert "group_ids" not in client.requests[1][3]


def test_disabled_strategy_error_is_translated(tmp_path: Path) -> None:
    client = FakeClient([{"status_code": 500, "data": {"code": 12905, "message": "disabled"}}])
    service, _ = service_with_client(tmp_path / "management.db", client)
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.execute_strategy("bot-1", "st-1"))
    assert error.value.status_code == 409
    assert "启用" in error.value.detail["message"]


def test_expired_join_request_error_is_translated(tmp_path: Path) -> None:
    client = FakeClient([{"status_code": 500, "data": {"code": 11004, "message": "invalid token"}}])
    service, _ = service_with_client(tmp_path / "management.db", client)
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.decide_join_request(
            "bot-1", group_openid="group-1", member_openid="member-1",
            join_request_id="expired-request", op="approve",
        ))
    assert error.value.status_code == 409
    assert "失效" in error.value.detail["message"]


def test_whitelist_is_split_into_official_batch_limit(tmp_path: Path) -> None:
    client = FakeClient()
    service, _ = service_with_client(tmp_path / "management.db", client)
    users = [str(10000000 + index) for index in range(10001)]
    result = asyncio.run(service.update_whitelist("bot-1", "st-1", "add", users))
    assert result["processed"] == 10001
    assert len(client.requests) == 2
    assert len(client.requests[0][3]["whitelist_users"]) == 10000
    assert len(client.requests[1][3]["whitelist_users"]) == 1


def test_group_registry_keeps_official_group_metadata_and_switches(tmp_path: Path) -> None:
    repository = GroupManagementRepository(tmp_path / "management.db")
    repository.remember_group(
        "bot-1", "group-openid", group_id="123456", group_name="测试群",
        group_finger_memo="群简介", group_class_text="科技",
        group_tags=["机器人", "开发"], group_member_num=88,
        source="group_info_api", info_synced=True,
    )
    group = repository.list_groups("bot-1")[0]
    assert group["group_id"] == "123456"
    assert group["group_tags"] == ["机器人", "开发"]
    assert group["group_member_num"] == 88
    settings = repository.update_settings(
        "bot-1", manual_approval_enabled=False, auto_approval_enabled=True,
    )
    assert settings["manual_approval_enabled"] is False
    assert settings["auto_approval_enabled"] is True


def test_disabling_auto_approval_disables_each_enabled_official_strategy(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 200, "data": {"strategies": [
            {"strategy_id": "enabled", "is_enable": "on"},
            {"strategy_id": "disabled", "is_enable": "off"},
        ]}},
        {"status_code": 200, "data": {"strategy_id": "enabled", "is_enable": "off"}},
    ])
    service, _ = service_with_client(tmp_path / "management.db", client)
    assert asyncio.run(service.disable_enabled_strategies("bot-1")) == 1
    assert client.requests[1] == (
        "PATCH", "/v2/groups/join_approval_strategy/enabled", None, {"is_enable": "off"},
    )
