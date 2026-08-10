import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.group_mute_repository import GroupMuteLeaseRepository
from app.services.group_mute_service import GroupMuteCoordinator


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def request(self, method, path, query, body):
        self.requests.append(body)
        return {"status_code": 200, "data": {}}


def coordinator(tmp_path: Path):
    repository = GroupMuteLeaseRepository(tmp_path / "leases.db")
    client = FakeClient()

    async def provider(_bot_id: str):
        return client

    return repository, client, GroupMuteCoordinator(repository, provider)


def expiry(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def test_releasing_verification_preserves_moderation_mute(tmp_path: Path) -> None:
    repository, client, service = coordinator(tmp_path)
    asyncio.run(service.apply("bot", "group", "member", source="verification", expire_at=expiry(30)))
    asyncio.run(service.apply("bot", "group", "member", source="moderation", expire_at=expiry(120)))

    result = asyncio.run(service.release("bot", "group", "member", source="verification"))

    assert result["still_muted"] is True
    assert client.requests[-1]["members"][0]["op"] == "update"
    assert [item["source"] for item in repository.active_leases("bot", "group", "member")] == ["moderation"]


def test_release_without_own_lease_does_not_unmute_other_source(tmp_path: Path) -> None:
    _, client, service = coordinator(tmp_path)
    asyncio.run(service.apply("bot", "group", "member", source="moderation", expire_at=expiry(60)))
    before = len(client.requests)
    result = asyncio.run(service.release("bot", "group", "member", source="verification"))
    assert result["still_muted"] is True
    assert len(client.requests) == before
