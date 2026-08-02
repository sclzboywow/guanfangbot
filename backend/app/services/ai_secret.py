from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretDecryptionError(ValueError):
    """Raised when a stored secret cannot be decrypted with the current key."""


def _fernet() -> Fernet:
    settings = get_settings()
    source = (settings.ai_credentials_secret or settings.session_secret).strip()
    if not source:
        raise RuntimeError("AI_CREDENTIALS_SECRET 或 SESSION_SECRET 未配置")
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("密钥不能为空")
    return _fernet().encrypt(cleaned.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(str(value).encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise SecretDecryptionError("已保存的 DeepSeek Key 无法解密，请重新保存") from exc
