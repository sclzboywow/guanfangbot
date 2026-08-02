from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "auth.db"
SESSION_TTL = timedelta(days=14)
PASSWORD_HASHER = PasswordHasher()


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> str:
    return utc_now_dt().isoformat()


class AuthRepository:
    def __init__(self, path: Path = DATABASE_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    disabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user
                    ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires
                    ON sessions(expires_at);
                """
            )

    @staticmethod
    def _user_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["disabled"] = bool(data.get("disabled"))
        return data

    def count_users(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            return int(row["count"] if row else 0)

    def get_first_admin(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM users
                WHERE role = 'admin' AND disabled = 0
                ORDER BY created_at ASC LIMIT 1
                """
            ).fetchone()
            return self._user_dict(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._user_dict(row)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        cleaned = email.strip().lower()
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE email = ?", (cleaned,)).fetchone()
            return self._user_dict(row)

    def create_user(self, *, email: str, password: str, role: str = "user") -> dict[str, Any]:
        cleaned = email.strip().lower()
        if not cleaned or "@" not in cleaned:
            raise ValueError("邮箱格式无效")
        if len(password) < 8:
            raise ValueError("密码至少 8 位")
        if role not in {"user", "admin"}:
            raise ValueError("无效角色")
        user_id = f"user-{uuid.uuid4().hex[:12]}"
        password_hash = PASSWORD_HASHER.hash(password)
        now = utc_now()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users (id, email, password_hash, role, disabled, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (user_id, cleaned, password_hash, role, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("该邮箱已注册") from exc
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError("无法创建用户")
        return user

    def verify_password(self, user: dict[str, Any], password: str) -> bool:
        try:
            return PASSWORD_HASHER.verify(str(user.get("password_hash") or ""), password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    def create_session(self, user_id: str) -> str:
        session_id = uuid.uuid4().hex + uuid.uuid4().hex
        now = utc_now_dt()
        expires_at = now + SESSION_TTL
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (id, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (session_id, user_id, expires_at.isoformat(), now.isoformat()),
            )
        return session_id

    def get_user_by_session(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.*
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.id = ? AND sessions.expires_at > ? AND users.disabled = 0
                """,
                (session_id, now),
            ).fetchone()
            return self._user_dict(row)

    def delete_session(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def purge_expired_sessions(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))


auth_repository = AuthRepository()
