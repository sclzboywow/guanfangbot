from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.services.auth_deps import (
    COOKIE_NAME,
    AuthUser,
    auth_rate_limiter,
    clear_session_cookie,
    client_ip,
    public_user,
    require_user,
    set_session_cookie,
)
from app.services.auth_repository import auth_repository

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("邮箱格式无效")
        if any(char.isspace() for char in cleaned):
            raise ValueError("邮箱不能包含空格")
        return cleaned


@router.post("/register")
def register(payload: AuthCredentials, request: Request, response: Response) -> dict:
    auth_rate_limiter.check(f"register:{client_ip(request)}")
    try:
        user = auth_repository.create_user(email=payload.email, password=payload.password, role="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session_id = auth_repository.create_session(str(user["id"]))
    set_session_cookie(response, session_id)
    return {"user": public_user(user)}


@router.post("/login")
def login(payload: AuthCredentials, request: Request, response: Response) -> dict:
    auth_rate_limiter.check(f"login:{client_ip(request)}")
    user = auth_repository.get_user_by_email(payload.email)
    if user is None or user.get("disabled") or not auth_repository.verify_password(user, payload.password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    session_id = auth_repository.create_session(str(user["id"]))
    set_session_cookie(response, session_id)
    return {"user": public_user(user)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    session_id = request.cookies.get(COOKIE_NAME, "")
    auth_repository.delete_session(session_id)
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: AuthUser = Depends(require_user)) -> dict:
    return {"user": public_user(user)}
