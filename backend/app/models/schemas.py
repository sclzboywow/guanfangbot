from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.event_catalog import EVENT_CODE_SET
from app.services.group_moderation_repository import (
    DEFAULT_CONTENT_KEYWORDS,
    DEFAULT_NICKNAME_KEYWORDS,
    DEFAULT_PENALTY_MINUTES,
)


class BotPublic(BaseModel):
    id: str
    name: str
    description: str = ""
    status: Literal["online", "offline", "created"] = "created"
    role: Literal["admin", "member"] = "admin"
    app_id: str
    has_secret: bool = False
    avatar_seed: int = 0
    avatar_url: str = ""
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

    @field_validator("event_scopes")
    @classmethod
    def validate_event_scopes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        unknown = sorted(set(cleaned) - EVENT_CODE_SET)
        if unknown:
            raise ValueError(f"包含未知事件类型：{', '.join(unknown)}")
        return cleaned


class GroupVerificationSettingsUpdate(BaseModel):
    enabled: bool = False
    min_operand: int = Field(default=1, ge=0, le=100)
    max_operand: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_range(self) -> "GroupVerificationSettingsUpdate":
        if self.max_operand < self.min_operand:
            raise ValueError("最大数字不能小于最小数字")
        return self


class GroupModerationSettingsUpdate(BaseModel):
    enabled: bool = False
    detect_mobile: bool = True
    detect_landline: bool = True
    detect_wechat: bool = True
    detect_content_keywords: bool = True
    detect_nickname_keywords: bool = True
    exempt_admins: bool = True
    penalty_minutes: list[int] = Field(default_factory=lambda: list(DEFAULT_PENALTY_MINUTES), min_length=1, max_length=8)
    permanent_after: int = Field(default=5, ge=2, le=20)
    escalation_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    warning_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    content_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_CONTENT_KEYWORDS), max_length=100)
    nickname_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_NICKNAME_KEYWORDS), max_length=100)

    @field_validator("penalty_minutes")
    @classmethod
    def validate_penalty_minutes(cls, value: list[int]) -> list[int]:
        cleaned = []
        for item in value:
            minutes = int(item)
            if minutes < 1 or minutes > 43200:
                raise ValueError("阶梯时长必须在 1 分钟到 30 天之间")
            cleaned.append(minutes)
        return cleaned

    @field_validator("content_keywords", "nickname_keywords")
    @classmethod
    def validate_keywords(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if any(len(item) > 40 for item in cleaned):
            raise ValueError("单个关键词不能超过 40 个字符")
        return cleaned


class LibraryDeliverySettingsUpdate(BaseModel):
    enabled: bool = False
    database_path: str = Field(default="/app/data/library.sqlite3", min_length=1, max_length=2048)
    table_name: str = Field(default="新网盘资料", min_length=1, max_length=128)
    title_column: str = Field(default="标题", min_length=1, max_length=128)
    category_column: str = Field(default="分类", min_length=1, max_length=128)
    size_column: str = Field(default="大小", min_length=1, max_length=128)
    fsid_column: str = Field(default="fsid", min_length=1, max_length=128)
    path_column: str = Field(default="网盘地址", min_length=1, max_length=128)
    access_token: str | None = Field(default=None, max_length=8192)
    clear_access_token: bool = False
    share_period: Literal[0, 1, 7, 30] = 7
    session_ttl_seconds: int = Field(default=180, ge=30, le=1800)
    api_url: str = Field(default="https://pan.baidu.com/rest/2.0/xpan/share", min_length=1, max_length=2048)
    api_method: str = Field(default="rapidshare", min_length=1, max_length=64)

    @field_validator(
        "database_path", "table_name", "title_column", "category_column",
        "size_column", "fsid_column", "path_column", "api_method",
    )
    @classmethod
    def clean_text_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or "\x00" in cleaned:
            raise ValueError("配置内容不能为空或包含空字符")
        return cleaned

    @field_validator("access_token")
    @classmethod
    def clean_access_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, value: str) -> str:
        cleaned = value.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("百度分享接口地址必须是完整的 http/https URL")
        return cleaned


class LibrarySearchTestRequest(BaseModel):
    bot_id: str = Field(min_length=1, max_length=128)
    keyword: str = Field(min_length=1, max_length=100)

    @field_validator("bot_id", "keyword")
    @classmethod
    def clean_search_fields(cls, value: str) -> str:
        return " ".join(value.split()).strip()


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
