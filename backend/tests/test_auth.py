from pathlib import Path

from fastapi.testclient import TestClient

from app.models.schemas import BotCreate
from app.services.auth_repository import AuthRepository
from app.services.bot_repository import BotRepository


def _build_client(tmp_path: Path, monkeypatch) -> TestClient:
    auth_repo = AuthRepository(tmp_path / "auth.db")
    bot_repo = BotRepository(tmp_path / "bots.json")

    import app.main as main_module
    import app.routers.auth as auth_router
    import app.routers.bots as bots_router
    import app.services.auth_deps as auth_deps
    import app.services.bootstrap as bootstrap
    from app.config import get_settings

    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    get_settings.cache_clear()

    monkeypatch.setattr(auth_deps, "auth_repository", auth_repo)
    monkeypatch.setattr(auth_deps, "bot_repository", bot_repo)
    monkeypatch.setattr(auth_router, "auth_repository", auth_repo)
    monkeypatch.setattr(bots_router, "bot_repository", bot_repo)
    monkeypatch.setattr(bootstrap, "auth_repository", auth_repo)
    monkeypatch.setattr(bootstrap, "bot_repository", bot_repo)
    monkeypatch.setattr(bootstrap, "baidu_oauth_repository", type("R", (), {
        "migrate_legacy_shared_token": staticmethod(lambda _owner: False),
    })())
    monkeypatch.setattr(main_module, "get_optional_user", auth_deps.get_optional_user)

    return TestClient(main_module.app)


def test_register_login_me_and_logout(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path, monkeypatch)
    assert client.get("/api/bots").status_code == 401

    register = client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert register.status_code == 200
    assert register.json()["user"]["email"] == "a@example.com"
    assert client.cookies.get("qqbot_session")

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "a@example.com"

    bots = client.get("/api/bots")
    assert bots.status_code == 200
    assert bots.json() == []

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_tenant_isolation(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path, monkeypatch)
    import app.routers.bots as bots_router
    import app.services.auth_deps as auth_deps

    auth_repo = auth_deps.auth_repository
    bot_repo = bots_router.bot_repository

    user_a = auth_repo.create_user(email="a@example.com", password="password123")
    auth_repo.create_user(email="b@example.com", password="password123")
    bot = bot_repo.create(
        BotCreate(
            app_id="111111111",
            client_secret="secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            callback_url="https://example.com/api/events/callback/111111111",
        ),
        owner_user_id=str(user_a["id"]),
    )

    login_b = client.post("/api/auth/login", json={"email": "b@example.com", "password": "password123"})
    assert login_b.status_code == 200
    assert client.get("/api/bots").json() == []
    assert client.get(f"/api/bots/{bot.id}").status_code == 404


def test_callback_stays_public(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path, monkeypatch)
    response = client.post("/api/events/callback/does-not-exist", json={"op": 0, "t": "READY", "d": {}})
    assert response.status_code != 401
