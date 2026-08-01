import pytest
from pydantic import ValidationError

from app.models.schemas import OpenApiRequest


def test_accepts_relative_path() -> None:
    item = OpenApiRequest(bot_id="bot-1", method="GET", path="/users/@me")
    assert item.path == "/users/@me"
    assert item.bot_id == "bot-1"


@pytest.mark.parametrize("path", ["https://evil.example", "//evil.example/path", "/../secret"])
def test_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        OpenApiRequest(bot_id="bot-1", method="GET", path=path)
