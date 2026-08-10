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
    owner_user_id: str = ""


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
    math_enabled: bool = True
    custom_question_enabled: bool = False
    combination_mode: Literal["all", "random_one"] = "all"
    custom_question: str = Field(default="请回答本群的入群验证问题", min_length=1, max_length=200)
    custom_answers: list[str] = Field(default_factory=list, max_length=20)
    custom_ignore_case: bool = True
    min_operand: int = Field(default=1, ge=0, le=100)
    max_operand: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=180, ge=30, le=3600)
    max_wrong_attempts: int = Field(default=3, ge=1, le=20)
    failure_mute_minutes: int = Field(default=1440, ge=1, le=43200)
    success_message: str = Field(default="验证通过，你现在可以正常发言。", min_length=1, max_length=200)

    @field_validator("success_message", "custom_question")
    @classmethod
    def normalize_verification_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("验证内容不能为空")
        return cleaned

    @field_validator("custom_answers")
    @classmethod
    def normalize_custom_answers(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(" ".join(str(item).split()) for item in value if str(item).strip()))
        if any(len(item) > 100 for item in cleaned):
            raise ValueError("单个自定义答案不能超过100字")
        return cleaned

    @model_validator(mode="after")
    def validate_range(self) -> "GroupVerificationSettingsUpdate":
        if self.max_operand < self.min_operand:
            raise ValueError("最大数字不能小于最小数字")
        if self.enabled and not (self.math_enabled or self.custom_question_enabled):
            raise ValueError("启用入群验证时，数学题和自定义问题至少开启一种")
        if self.custom_question_enabled and not self.custom_answers:
            raise ValueError("启用自定义问题时，请至少设置一个正确答案")
        return self


class OfficialJoinDecision(BaseModel):
    group_openid: str = Field(min_length=1, max_length=128)
    member_openid: str = Field(min_length=1, max_length=128)
    join_request_id: str = Field(min_length=1, max_length=2048)
    op: Literal["approve", "decline"]
    reject_reason: str = Field(default="", max_length=200)
    add_to_member_blacklist: bool = False

    @field_validator("group_openid", "member_openid", "join_request_id")
    @classmethod
    def clean_official_ids(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char.isspace() for char in cleaned):
            raise ValueError("标识不能为空或包含空格")
        return cleaned

    @field_validator("reject_reason")
    @classmethod
    def clean_reject_reason(cls, value: str) -> str:
        return " ".join(value.split())


class GroupManagementSettingsUpdate(BaseModel):
    manual_approval_enabled: bool = True
    auto_approval_enabled: bool = True
    keyword_approve_enabled: bool = False
    keyword_reject_enabled: bool = False
    approve_keywords: list[str] = Field(default_factory=list, max_length=100)
    reject_keywords: list[str] = Field(default_factory=list, max_length=100)
    reject_reason: str = Field(default="", max_length=200)
    reject_blacklist: bool = False

    @staticmethod
    def _clean_keywords(value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            word = " ".join(str(item).split()).strip()
            if not word:
                continue
            if len(word) > 50:
                raise ValueError("单个关键词最长 50 个字符")
            key = word.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(word)
            if len(cleaned) > 100:
                raise ValueError("关键词最多 100 个")
        return cleaned

    @field_validator("approve_keywords", "reject_keywords")
    @classmethod
    def clean_keyword_lists(cls, value: list[str]) -> list[str]:
        return cls._clean_keywords(value)

    @field_validator("reject_reason")
    @classmethod
    def clean_keyword_reject_reason(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_keyword_reject_reason(self) -> "GroupManagementSettingsUpdate":
        if self.keyword_reject_enabled and not self.reject_reason:
            raise ValueError("开启关键词自动拒绝时，必须填写拒绝理由")
        return self


class OfficialMuteMember(BaseModel):
    op: Literal["add", "update", "del"]
    member_openid: str = Field(min_length=1, max_length=128)
    mute_expire_at: str = Field(default="", max_length=64)

    @field_validator("member_openid")
    @classmethod
    def clean_mute_member(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char.isspace() for char in cleaned):
            raise ValueError("成员 OpenID 格式不正确")
        return cleaned

    @model_validator(mode="after")
    def validate_expiry(self) -> "OfficialMuteMember":
        self.mute_expire_at = self.mute_expire_at.strip()
        if self.op != "del" and not self.mute_expire_at:
            raise ValueError("新增或修改禁言时必须选择结束时间")
        return self


class OfficialMuteUpdate(BaseModel):
    group_openid: str = Field(min_length=1, max_length=128)
    members: list[OfficialMuteMember] = Field(min_length=1, max_length=10)

    @field_validator("group_openid")
    @classmethod
    def clean_mute_group(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char.isspace() for char in cleaned):
            raise ValueError("群 OpenID 格式不正确")
        return cleaned


class ApprovalStrategyCreate(BaseModel):
    group_mode: Literal["group_openids", "group_ids"] = "group_openids"
    groups: list[str] = Field(min_length=1, max_length=100)
    is_enable: Literal["on", "off"] = "on"
    expire_at: str | None = Field(default=None, max_length=64)
    remark: str = Field(default="", max_length=255)

    @field_validator("groups")
    @classmethod
    def clean_strategy_groups(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if not cleaned:
            raise ValueError("请至少填写一个群")
        if any(any(char.isspace() for char in item) for item in cleaned):
            raise ValueError("群标识不能包含空格")
        return cleaned

    @field_validator("remark")
    @classmethod
    def clean_strategy_remark(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_group_id_mode(self) -> "ApprovalStrategyCreate":
        if self.group_mode == "group_ids" and any(not item.isdigit() for item in self.groups):
            raise ValueError("QQ群号只能填写数字")
        if self.expire_at is not None:
            self.expire_at = self.expire_at.strip() or None
        return self


class ApprovalGroupAction(BaseModel):
    op: Literal["add", "del"]
    group_mode: Literal["group_openids", "group_ids"]
    groups: list[str] = Field(min_length=1, max_length=100)

    @field_validator("groups")
    @classmethod
    def clean_group_action_values(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @model_validator(mode="after")
    def validate_group_action_mode(self) -> "ApprovalGroupAction":
        if not self.groups:
            raise ValueError("请填写需要增删的群")
        if self.group_mode == "group_ids" and any(not item.isdigit() for item in self.groups):
            raise ValueError("QQ群号只能填写数字")
        return self


class ApprovalStrategyUpdate(BaseModel):
    is_enable: Literal["on", "off"] | None = None
    expire_at: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=255)
    group_action: ApprovalGroupAction | None = None

    @model_validator(mode="after")
    def require_strategy_change(self) -> "ApprovalStrategyUpdate":
        if self.is_enable is None and self.expire_at is None and self.remark is None and self.group_action is None:
            raise ValueError("请至少修改一项策略内容")
        return self


class ApprovalWhitelistUpdate(BaseModel):
    op: Literal["add", "del"]
    whitelist_users: list[str] = Field(min_length=1, max_length=100000)

    @field_validator("whitelist_users")
    @classmethod
    def validate_qq_numbers(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if not cleaned or any(not item.isdigit() for item in cleaned):
            raise ValueError("白名单只能填写QQ号码，每行一个或使用逗号分隔")
        return cleaned


class GroupModerationSettingsUpdate(BaseModel):
    enabled: bool = False
    detect_mobile: bool = True
    detect_landline: bool = True
    detect_wechat: bool = True
    detect_content_keywords: bool = True
    detect_nickname_keywords: bool = True
    exempt_admins: bool = True
    use_official_mute: bool = True
    retract_merged_messages: bool = False
    retract_group_cards: bool = False
    merged_message_action: Literal["retract", "mute"] = "retract"
    group_card_action: Literal["retract", "mute"] = "retract"
    special_rule_mute_minutes: int = Field(default=60, ge=1, le=43200)
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
    share_period: Literal[0, 1, 7, 30] = 7
    session_ttl_seconds: int = Field(default=180, ge=30, le=1800)
    api_url: str = Field(default="https://pan.baidu.com/rest/2.0/xpan/share", min_length=1, max_length=2048)
    api_method: str = Field(default="set", min_length=1, max_length=64)

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
