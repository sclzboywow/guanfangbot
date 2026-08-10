from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.schemas import BotCreate, BotUpdate
from app.services.bot_repository import BotRepository
from app.services.event_catalog import EVENT_CODE_SET, EVENT_GROUPS


def test_complete_event_catalog_has_44_unique_events() -> None:
    codes = [
        event["code"]
        for group in EVENT_GROUPS
        for event in group["events"]
    ]
    assert len(codes) == 44
    assert len(set(codes)) == 44
    assert set(codes) == EVENT_CODE_SET
    assert {
        "C2C_MESSAGE_CREATE",
        "GROUP_MESSAGE_CREATE",
        "GROUP_JOIN_REQUEST",
        "SUBSCRIBE_MESSAGE_STATUS",
        "OPEN_FORUM_THREAD_CREATE",
        "AUDIO_OFF_MIC",
        "INTERACTION_CREATE",
    }.issubset(EVENT_CODE_SET)


def test_event_scopes_reject_unknown_codes() -> None:
    update = BotUpdate(event_scopes=["C2C_MESSAGE_CREATE", "INTERACTION_CREATE"])
    assert update.event_scopes == ["C2C_MESSAGE_CREATE", "INTERACTION_CREATE"]

    with pytest.raises(ValidationError):
        BotUpdate(event_scopes=["NOT_A_REAL_QQ_EVENT"])


def test_detection_state_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "bots.json"
    repository = BotRepository(path)
    bot = repository.create(
        BotCreate(
            app_id="123456789",
            client_secret="test-secret",
            callback_url="https://example.com/api/events/callback/123456789",
        ),
        owner_user_id="user-test",
    )

    repository.mark_callback_verified(bot.id, "2026-08-02T00:00:00+00:00")
    repository.mark_event_observed(bot.id, "C2C_MESSAGE_CREATE", "2026-08-02T00:01:00+00:00")

    reloaded = BotRepository(path)
    detection = reloaded.get_event_detection(bot.id)
    assert detection is not None
    verified_at, observed = detection
    assert verified_at == "2026-08-02T00:00:00+00:00"
    assert observed["C2C_MESSAGE_CREATE"] == "2026-08-02T00:01:00+00:00"
