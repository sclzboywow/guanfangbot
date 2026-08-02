from app.models.schemas import BotCreate
from app.routers.events import _resolve_credentials
from app.services.bot_repository import BotRepository


def test_explicit_unknown_app_id_does_not_fall_back_to_other_bot(tmp_path, monkeypatch) -> None:
    repository = BotRepository(tmp_path / "bots.json")
    repository.create(
        BotCreate(
            app_id="102825384",
            client_secret="secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            callback_url="https://bot.yzdoc.cn/api/events/callback/102825384",
        ),
        owner_user_id="user-test",
    )
    monkeypatch.setattr("app.routers.events.bot_repository", repository)

    assert _resolve_credentials("1905266006") is None
    resolved = _resolve_credentials(None)
    assert resolved is not None
    assert resolved[1] == "102825384"
    matched = _resolve_credentials("102825384")
    assert matched is not None
    assert matched[1] == "102825384"
