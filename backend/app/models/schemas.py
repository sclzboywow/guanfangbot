from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class BotPublic(BaseModel):
    id: str
    name: str
    description: str = ""
    status: Literal["online", "offline", "created"] = "created"
    role: Literal["admin", "member"] = "admin"
    app_id: str
    has_secret: bool = False
    avatar_seed: int = 0
    updated_at: str
    callback_url: str = ""
    event_scopes: list[str] = Field(default_factory=list)


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=120)
    app_id: str = Field(min_length=1, max_length=64)
    client_secret: str = Field(min_length=1, max_length=256)
    status: Literal["online", "offline", "created"] = "created"
    callback_url: str = ""
    event_scopes: list[str] = Field(default_factory=list)


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=120)
    app_id: str | None = Field(default=None, min_length=1, max_length=64)
    client_secret: str | None = Field(default=None, min_length=1, max_length=256)
    status: Literal["online", "offline", "created"] | None = None
    callback_url: str | None = None
    event_scopes: list[str] | None = None


class OpenApiRequest(BaseModel):
    bot_id: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str
    query: dict[str, str] | None = None
    body: Any | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/"):
            raise ValueError("path 必须以 / 开头")
        if value.startswith("//") or "://" in value or ".." in value:
            raise ValueError("只允许安全的相对 API 路径")
        return value
