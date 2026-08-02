import asyncio
from types import SimpleNamespace

import httpx

from app.config import Settings
from app.services.ai_repository import AiRepository
from app.services.ai_secret import decrypt_secret, encrypt_secret
from app.services.deepseek_client import DeepSeekClient
from app.services.qqbot_client import QQBotClient


def test_ai_repository_enforces_one_profile_and_deduplicates_jobs(tmp_path) -> None:
    repository = AiRepository(tmp_path / "ai.db")
    first = repository.save_profile("bot-1", {"enabled": True, "identity_name": "小栈"})
    second = repository.save_profile("bot-1", {"enabled": False, "identity_name": "新名字"})
    assert first["bot_id"] == "bot-1"
    assert second["identity_name"] == "新名字"
    assert second["enabled"] is False

    job = repository.enqueue_job(
        bot_id="bot-1",
        owner_user_id="user-1",
        user_openid="openid-1",
        trigger_message_id="message-1",
        trigger_content="你好",
    )
    duplicate = repository.enqueue_job(
        bot_id="bot-1",
        owner_user_id="user-1",
        user_openid="openid-1",
        trigger_message_id="message-1",
        trigger_content="重复",
    )
    assert job is not None
    assert duplicate is None
    claimed = repository.claim_next_job()
    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1


def test_ai_jobs_are_serialized_per_conversation(tmp_path) -> None:
    repository = AiRepository(tmp_path / "ai.db")
    for message_id in ("m1", "m2"):
        repository.enqueue_job(
            bot_id="bot-1",
            owner_user_id="user-1",
            user_openid="openid-1",
            trigger_message_id=message_id,
            trigger_content=message_id,
        )
    first = repository.claim_next_job()
    assert first is not None and first["trigger_message_id"] == "m1"
    assert repository.claim_next_job() is None
    repository.complete_job(
        int(first["id"]),
        output_text="ok",
        output_image_key="",
        model="deepseek-v4-flash",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        qq_message_id="qq-1",
        delivery_mode="quote",
    )
    second = repository.claim_next_job()
    assert second is not None and second["trigger_message_id"] == "m2"


def test_user_key_is_encrypted_at_rest(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_secret.get_settings",
        lambda: SimpleNamespace(ai_credentials_secret="test-encryption-key", session_secret="fallback"),
    )
    encrypted = encrypt_secret("sk-this-is-private")
    assert "sk-this-is-private" not in encrypted
    assert decrypt_secret(encrypted) == "sk-this-is-private"


def test_deepseek_json_plan_filters_unknown_image_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        payload = __import__("json").loads((await request.aread()).decode())
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": '{"text":"你好呀","image_key":"missing"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            },
        )

    settings = Settings(deepseek_api_base="https://api.deepseek.test", deepseek_request_timeout=5)
    client = DeepSeekClient("sk-test", settings, transport=httpx.MockTransport(handler))
    reply = asyncio.run(client.complete(
        profile={
            "model": "deepseek-v4-flash",
            "thinking_enabled": False,
            "identity_name": "小栈",
            "allow_images": True,
            "image_assets": [{"key": "happy", "label": "开心", "description": "开心时发送"}],
            "max_tokens": 300,
        },
        history=[{"role": "user", "content": "你好"}],
        bot_id="bot-1",
        user_openid="openid-1",
    ))
    assert reply.text == "你好呀"
    assert reply.image_key == ""
    assert reply.total_tokens == 14


def test_enqueue_group_job(tmp_path) -> None:
    from app.services.ai_reply_service import _clean_trigger_text

    assert _clean_trigger_text("<@!12345>  你好呀") == "你好呀"
    repository = AiRepository(tmp_path / "ai.db")
    job = repository.enqueue_job(
        bot_id="bot-1",
        owner_user_id="user-1",
        user_openid="member-1",
        trigger_message_id="g-msg-1",
        trigger_content=_clean_trigger_text("<@!bot> 帮我看看"),
        channel="group",
        group_openid="group-1",
    )
    assert job is not None
    assert job["channel"] == "group"
    assert job["group_openid"] == "group-1"
    assert job["trigger_content"] == "帮我看看"


def test_qq_c2c_media_uses_upload_then_msg_type_seven() -> None:
    captured = []

    class CapturingClient(QQBotClient):
        async def request(self, method, path, query, body):  # type: ignore[override]
            captured.append((method, path, body))
            if path.endswith("/files"):
                return {"status_code": 200, "data": {"file_info": "file-token"}, "headers": {}}
            return {"status_code": 200, "data": {"id": "message-id"}, "headers": {}}

    client = CapturingClient("bot-1", "app", "secret")
    upload = asyncio.run(client.upload_c2c_media("openid", "https://example.com/image.png"))
    sent = asyncio.run(client.send_c2c_media("openid", upload["data"]["file_info"], msg_id="source", msg_seq=2))
    assert sent["status_code"] == 200
    assert captured[0][1] == "/v2/users/openid/files"
    assert captured[0][2]["file_type"] == 1
    assert captured[1][2] == {
        "msg_type": 7,
        "media": {"file_info": "file-token"},
        "msg_id": "source",
        "msg_seq": 2,
    }
