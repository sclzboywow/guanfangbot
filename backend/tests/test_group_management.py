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


def test_existing_group_without_name_refreshes_info_on_event(tmp_path: Path) -> None:
    client = FakeClient([
        {
            "status_code": 200,
            "data": {
                "group_openid": "group-1",
                "group_name": "补全后的群名",
                "group_member_num": 12,
            },
        }
    ])
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.remember_group("bot-1", "group-1", source="event:GROUP_MESSAGE_CREATE")
    assert repository.list_groups("bot-1")[0]["group_name"] == ""

    asyncio.run(service.handle_event("bot-1", "GROUP_MESSAGE_CREATE", {
        "d": {"group_openid": "group-1", "id": "msg-1", "content": "hi"},
    }))

    group = repository.list_groups("bot-1")[0]
    assert group["group_name"] == "补全后的群名"
    assert group["group_member_num"] == 12
    assert client.requests[0][0:2] == ("GET", "/v2/groups/group-1/info")


def test_join_request_token_rotation_replaces_pending_duplicate(tmp_path: Path) -> None:
    repository = GroupManagementRepository(tmp_path / "management.db")
    first = repository.upsert_join_request(
        "bot-1",
        {
            "group_openid": "group-1",
            "join_request_id": "token-old",
            "member_openid": "member-1",
            "username": "申请人",
            "apply_at": "2026-08-11T01:00:00+08:00",
        },
        source="test",
    )
    assert first is not None
    second = repository.upsert_join_request(
        "bot-1",
        {
            "group_openid": "group-1",
            "join_request_id": "token-new",
            "member_openid": "member-1",
            "username": "申请人",
            "apply_at": "2026-08-11T01:00:00+08:00",
            "verify_info": {"verify_message": "新令牌"},
        },
        source="test",
    )
    assert second is not None
    requests = repository.list_join_requests("bot-1")
    assert len(requests) == 1
    assert requests[0]["join_request_id"] == "token-new"
    assert requests[0]["verify_info"]["verify_message"] == "新令牌"


def test_sync_prunes_stale_pending_tokens_after_full_list(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 200, "data": {"list": [{
            "join_request_id": "token-live", "member_openid": "member-live", "username": "在列",
        }], "next_cursor": ""}},
    ])
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.upsert_join_request(
        "bot-1",
        {
            "group_openid": "group-1",
            "join_request_id": "token-stale",
            "member_openid": "member-gone",
            "username": "已不在官方列表",
        },
        source="seed",
    )
    result = asyncio.run(service.sync_join_requests("bot-1", "group-1"))
    assert result["pruned"] == 1
    requests = repository.list_join_requests("bot-1")
    assert len(requests) == 1
    assert requests[0]["join_request_id"] == "token-live"


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
    assert result["synced"] == 1
    assert result["pages"] == 2
    assert result["truncated"] is False
    assert result["pruned"] == 0
    assert result["keyword"] == {"checked": 0, "approved": 0, "declined": 0, "failed": 0}
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


def test_scheduled_poll_skips_groups_where_bot_is_not_admin(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 500, "data": {"message": "not group admin", "code": 11703, "err_code": 11703}},
        {"status_code": 200, "data": {"list": [{
            "join_request_id": "request-ok", "member_openid": "member-ok", "username": "可管",
        }], "next_cursor": ""}},
    ])
    service, repository = service_with_client(tmp_path / "management.db", client)
    # list_group_targets is newest-first; remember admin group first so no-admin is polled first.
    repository.remember_group("bot-1", "group-admin", source="event")
    repository.remember_group("bot-1", "group-no-admin", source="event")

    import app.services.group_management_service as module
    original_gap = module.JOIN_REQUEST_POLL_GROUP_GAP_SECONDS
    module.JOIN_REQUEST_POLL_GROUP_GAP_SECONDS = 0
    try:
        summary = asyncio.run(service.poll_all_join_requests())
    finally:
        module.JOIN_REQUEST_POLL_GROUP_GAP_SECONDS = original_gap

    assert summary["targets"] == 2
    assert summary["skipped_not_admin"] == 1
    assert summary["groups"] == 1
    assert summary["failed"] == 0
    assert summary["synced"] == 1
    assert repository.list_join_requests("bot-1")[0]["join_request_id"] == "request-ok"


def test_scheduled_poll_syncs_all_remembered_groups_quietly(tmp_path: Path) -> None:
    client = FakeClient([
        {"status_code": 200, "data": {"list": [{
            "join_request_id": "request-a", "member_openid": "member-a", "username": "甲",
        }], "next_cursor": ""}},
        {"status_code": 200, "data": {"list": [{
            "join_request_id": "request-b", "member_openid": "member-b", "username": "乙",
        }], "next_cursor": ""}},
    ])
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.remember_group("bot-1", "group-a", source="event")
    repository.remember_group("bot-1", "group-b", source="event")

    # Avoid sleeping between groups during the unit test.
    import app.services.group_management_service as module
    original_gap = module.JOIN_REQUEST_POLL_GROUP_GAP_SECONDS
    module.JOIN_REQUEST_POLL_GROUP_GAP_SECONDS = 0
    try:
        summary = asyncio.run(service.poll_all_join_requests())
    finally:
        module.JOIN_REQUEST_POLL_GROUP_GAP_SECONDS = original_gap

    assert summary["targets"] == 2
    assert summary["groups"] == 2
    assert summary["synced"] == 2
    assert summary["failed"] == 0
    requests = repository.list_join_requests("bot-1")
    assert {item["join_request_id"] for item in requests} == {"request-a", "request-b"}
    assert len(client.requests) == 2
    # Quiet mode should not write a per-page sync log; only optional summary when synced>0.
    actions = [item["action"] for item in repository.list_logs("bot-1")]
    assert "sync_join_requests" not in actions
    assert "scheduled_join_request_poll" in actions


def _pending_request(verify_info: dict) -> dict:
    return {
        "group_openid": "group-1",
        "join_request_id": "request-kw",
        "member_openid": "member-1",
        "username": "申请人",
        "verify_info": verify_info,
    }


def test_keyword_auto_approve_on_answer_hit(tmp_path: Path) -> None:
    client = FakeClient()
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.update_settings(
        "bot-1",
        manual_approval_enabled=False,
        auto_approval_enabled=True,
        keyword_approve_enabled=True,
        approve_keywords=["你好", "通过"],
    )
    request = repository.upsert_join_request(
        "bot-1",
        _pending_request({
            "verify_message": "",
            "review_qa_list": [{"question": "群满 进450654168", "answer": "你好世界"}],
        }),
        source="test",
    )
    result = asyncio.run(service.apply_keyword_rules("bot-1", request))
    assert result == {"decision": "approve", "matched": ["你好"]}
    assert client.requests[0][3]["op"] == "approve"
    assert repository.list_join_requests("bot-1")[0]["status"] == "approved"
    assert repository.list_logs("bot-1")[0]["action"] == "keyword_auto_approve"
    assert "matched=你好" in repository.list_logs("bot-1")[0]["detail"]


def test_keyword_auto_decline_uses_reject_reason(tmp_path: Path) -> None:
    client = FakeClient()
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.update_settings(
        "bot-1",
        manual_approval_enabled=True,
        auto_approval_enabled=True,
        keyword_reject_enabled=True,
        reject_keywords=["广告", "引流"],
        reject_reason="验证内容不合规",
        reject_blacklist=False,
    )
    request = repository.upsert_join_request(
        "bot-1",
        _pending_request({"verify_message": "我来做广告推广", "review_qa_list": []}),
        source="test",
    )
    result = asyncio.run(service.apply_keyword_rules("bot-1", request))
    assert result == {"decision": "decline", "matched": ["广告"]}
    body = client.requests[0][3]
    assert body["op"] == "decline"
    assert body["reject_reason"] == "验证内容不合规"
    assert body["add_to_member_blacklist"] is False
    assert repository.list_join_requests("bot-1")[0]["status"] == "declined"
    assert repository.list_logs("bot-1")[0]["action"] == "keyword_auto_decline"


def test_keyword_conflict_prefers_reject(tmp_path: Path) -> None:
    client = FakeClient()
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.update_settings(
        "bot-1",
        manual_approval_enabled=True,
        auto_approval_enabled=True,
        keyword_approve_enabled=True,
        keyword_reject_enabled=True,
        approve_keywords=["你好"],
        reject_keywords=["广告"],
        reject_reason="拒绝优先",
    )
    request = repository.upsert_join_request(
        "bot-1",
        _pending_request({"verify_message": "你好，我做广告", "review_qa_list": []}),
        source="test",
    )
    result = asyncio.run(service.apply_keyword_rules("bot-1", request))
    assert result["decision"] == "decline"
    assert result["matched"] == ["广告"]
    assert client.requests[0][3]["op"] == "decline"


def test_keyword_rules_disabled_leave_pending(tmp_path: Path) -> None:
    client = FakeClient()
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.update_settings(
        "bot-1",
        manual_approval_enabled=True,
        auto_approval_enabled=True,
        keyword_approve_enabled=False,
        keyword_reject_enabled=False,
        approve_keywords=["你好"],
        reject_keywords=["广告"],
        reject_reason="不会用到",
    )
    request = repository.upsert_join_request(
        "bot-1",
        _pending_request({"verify_message": "你好广告", "review_qa_list": []}),
        source="test",
    )
    assert asyncio.run(service.apply_keyword_rules("bot-1", request)) is None
    assert client.requests == []
    assert repository.list_join_requests("bot-1")[0]["status"] == "pending"


def test_keyword_reject_schema_requires_reason() -> None:
    from pydantic import ValidationError

    from app.models.schemas import GroupManagementSettingsUpdate

    with pytest.raises(ValidationError):
        GroupManagementSettingsUpdate(
            keyword_reject_enabled=True,
            reject_reason="",
            reject_keywords=["广告"],
        )
    ok = GroupManagementSettingsUpdate(
        keyword_reject_enabled=True,
        reject_reason="不合规",
        reject_keywords=[" 广告 ", "广告", ""],
        approve_keywords=["你好"],
    )
    assert ok.reject_keywords == ["广告"]
    assert ok.reject_reason == "不合规"


def test_keyword_does_not_match_admin_question_or_nickname(tmp_path: Path) -> None:
    client = FakeClient()
    service, repository = service_with_client(tmp_path / "management.db", client)
    repository.update_settings(
        "bot-1",
        manual_approval_enabled=True,
        auto_approval_enabled=True,
        keyword_approve_enabled=True,
        approve_keywords=["群满", "申请人"],
    )
    request = repository.upsert_join_request(
        "bot-1",
        {
            **_pending_request({
                "verify_message": "随便",
                "review_qa_list": [{"question": "群满 进450654168", "answer": "ok"}],
            }),
            "username": "申请人",
        },
        source="test",
    )
    assert asyncio.run(service.apply_keyword_rules("bot-1", request)) is None
    assert client.requests == []
