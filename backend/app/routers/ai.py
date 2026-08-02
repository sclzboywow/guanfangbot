from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.schemas import BotUpdate
from app.services.ai_repository import DEFAULT_PROFILE, ai_repository
from app.services.ai_secret import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.services.auth_deps import AuthUser, require_owned_bot, require_user
from app.services.bot_repository import bot_repository
from app.services.deepseek_client import DeepSeekClient, DeepSeekError

router = APIRouter(prefix="/ai", tags=["ai"])
ASSET_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")


class CredentialSaveRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value: str) -> str:
        cleaned = value.strip()
        if any(char.isspace() for char in cleaned):
            raise ValueError("API Key 不能包含空格")
        return cleaned


class ImageAsset(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    url: str = Field(min_length=8, max_length=2048)

    @field_validator("key")
    @classmethod
    def clean_key(cls, value: str) -> str:
        cleaned = value.strip()
        if not ASSET_KEY_RE.fullmatch(cleaned):
            raise ValueError("素材键只允许字母、数字、下划线和短横线")
        return cleaned

    @field_validator("label", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split()).strip()

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        cleaned = value.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("图片素材必须使用不含账号密码的 HTTPS 地址")
        return cleaned


class AiProfileUpdate(BaseModel):
    enabled: bool = False
    model: Literal["deepseek-v4-flash", "deepseek-v4-pro"] = "deepseek-v4-flash"
    thinking_enabled: bool = False
    identity_name: str = Field(default="QQ AI 伙伴", min_length=1, max_length=80)
    role_description: str = Field(default=DEFAULT_PROFILE["role_description"], max_length=2000)
    relationship_description: str = Field(default=DEFAULT_PROFILE["relationship_description"], max_length=1000)
    speaking_style: str = Field(default=DEFAULT_PROFILE["speaking_style"], max_length=1000)
    response_length: Literal["brief", "short", "normal", "detailed"] = "short"
    restrictions: str = Field(default=DEFAULT_PROFILE["restrictions"], max_length=2000)
    custom_prompt: str = Field(default="", max_length=6000)
    reply_mode: Literal["auto", "quote", "normal"] = "auto"
    quote_fallback: bool = True
    context_turns: int = Field(default=12, ge=1, le=30)
    max_tokens: int = Field(default=600, ge=64, le=4000)
    allow_images: bool = False
    image_assets: list[ImageAsset] = Field(default_factory=list, max_length=20)
    failure_message: str = Field(default=DEFAULT_PROFILE["failure_message"], max_length=500)

    @field_validator(
        "identity_name", "role_description", "relationship_description", "speaking_style",
        "restrictions", "custom_prompt", "failure_message",
    )
    @classmethod
    def normalize_newlines(cls, value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()

    @model_validator(mode="after")
    def unique_asset_keys(self) -> "AiProfileUpdate":
        keys = [item.key for item in self.image_assets]
        if len(keys) != len(set(keys)):
            raise ValueError("图片素材键不能重复")
        return self


class AiTestRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _owner_id_for_bot(bot_id: str) -> str:
    owner_user_id = bot_repository.get_owner_user_id(bot_id)
    if not owner_user_id:
        raise HTTPException(status_code=409, detail="机器人尚未分配所属用户")
    return owner_user_id


def _credential_key(owner_user_id: str) -> str:
    encrypted = ai_repository.get_encrypted_credential(owner_user_id)
    if not encrypted:
        raise HTTPException(status_code=409, detail="尚未配置 DeepSeek API Key")
    try:
        return decrypt_secret(encrypted)
    except SecretDecryptionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/credential")
def credential_status(user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return ai_repository.credential_status(str(user["id"]))


@router.put("/credential")
async def save_credential(
    payload: CredentialSaveRequest,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    try:
        models = await DeepSeekClient(payload.api_key).validate()
    except DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    hint = payload.api_key[-4:] if len(payload.api_key) >= 4 else "****"
    ai_repository.save_credential(str(user["id"]), encrypt_secret(payload.api_key), f"••••{hint}")
    return {**ai_repository.credential_status(str(user["id"])), "models": models}


@router.post("/credential/test")
async def test_credential(user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    api_key = _credential_key(str(user["id"]))
    try:
        models = await DeepSeekClient(api_key).validate()
    except DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "models": models}


@router.delete("/credential")
def delete_credential(user: AuthUser = Depends(require_user)) -> dict[str, bool]:
    return {"ok": ai_repository.delete_credential(str(user["id"]))}


@router.get("/bots/{bot_id}")
def bot_ai_status(
    bot_id: str,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    owner_user_id = _owner_id_for_bot(bot_id)
    credential = ai_repository.credential_status(owner_user_id)
    return {
        "bot_id": bot.id,
        "bot_name": bot.name,
        "profile": ai_repository.get_profile(bot_id),
        "credential": {
            "configured": credential["configured"],
            "key_hint": credential["key_hint"] if owner_user_id == str(user["id"]) else "",
            "owner_is_current_user": owner_user_id == str(user["id"]),
        },
        "jobs": ai_repository.list_jobs(bot_id, 40),
        "counts": ai_repository.counts(bot_id),
        "required_event": "C2C_MESSAGE_CREATE",
        "event_configured": "C2C_MESSAGE_CREATE" in set(bot.event_scopes),
    }


@router.put("/bots/{bot_id}")
def save_bot_ai_profile(
    bot_id: str,
    payload: AiProfileUpdate,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    bot = require_owned_bot(bot_id, user)
    owner_user_id = _owner_id_for_bot(bot_id)
    if payload.enabled and not ai_repository.credential_status(owner_user_id)["configured"]:
        raise HTTPException(status_code=409, detail="请先保存并验证 DeepSeek API Key")
    profile = ai_repository.save_profile(bot_id, payload.model_dump())
    if payload.enabled and "C2C_MESSAGE_CREATE" not in set(bot.event_scopes):
        bot_repository.update(bot_id, BotUpdate(event_scopes=[*bot.event_scopes, "C2C_MESSAGE_CREATE"]))
    return {"profile": profile}


@router.post("/bots/{bot_id}/test")
async def test_bot_ai_profile(
    bot_id: str,
    payload: AiTestRequest,
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    owner_user_id = _owner_id_for_bot(bot_id)
    api_key = _credential_key(owner_user_id)
    profile = ai_repository.get_profile(bot_id)
    try:
        reply = await DeepSeekClient(api_key).complete(
            profile=profile,
            history=[{"role": "user", "content": payload.prompt}],
            bot_id=bot_id,
            user_openid="settings-test",
        )
    except DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "text": reply.text,
        "image_key": reply.image_key,
        "model": reply.model,
        "usage": {
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "total_tokens": reply.total_tokens,
        },
    }


@router.get("/jobs")
def list_ai_jobs(
    bot_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUser = Depends(require_user),
) -> dict[str, Any]:
    require_owned_bot(bot_id, user)
    return {"jobs": ai_repository.list_jobs(bot_id, limit), "counts": ai_repository.counts(bot_id)}
