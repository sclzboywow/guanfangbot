from typing import Any, Literal
from urllib.parse import urlparse

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
    app_id: str = Field(min_length=1, max_length=64)
    client_secret: str = Field(min_length=1, max_length=256)
    callback_url: str = Field(min_length=1, max_length=2048)

    @field_validator("app_id")
    @classmethod
    def validate_app_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        if any(char.isspace() for char in value) or any(char in value for char in "/?#"):
            raise ValueError("AppID 不能包含空格或路径字符")
        return value

    @field_validator("client_secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("callback_url")
    @classmethod
    def validate_callback_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("回调地址必须是完整的 http/https URL")
        return value


class BotUpdate(BaseModel):
    app_id: str | None = Field(default=None, min_length=1, max_length=64)
    client_secret: str | None = Field(default=None, min_length=1, max_length=256)
    callback_url: str | None = Field(default=None, min_length=1, max_length=2048)
    event_scopes: list[str] | None = None

    @field_validator("app_id")
    @classmethod
    def validate_optional_app_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        if any(char.isspace() for char in value) or any(char in value for char in "/?#"):
            raise ValueError("AppID 不能包含空格或路径字符")
        return value

    @field_validator("client_secret")
    @classmethod
    def validate_optional_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("callback_url")
    @classmethod
    def validate_optional_callback_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("回调地址必须是完整的 http/https URL")
        return value


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
