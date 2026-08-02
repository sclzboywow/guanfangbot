from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "baidu_oauth.db"
ACCOUNT_ID = "shared-library"


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> str:
    return utc_now_dt().isoformat()


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class BaiduOAuthRepository:
    """Stores one shared Baidu Netdisk authorization for all QQ library users."""

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
                CREATE TABLE IF NOT EXISTS baidu_oauth_tokens (
                    account_id TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL DEFAULT '',
                    refresh_token TEXT NOT NULL DEFAULT '',
                    expires_at TEXT,
                    scope TEXT NOT NULL DEFAULT '',
                    authorized_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS baidu_oauth_sessions (
                    id TEXT PRIMARY KEY,
                    requested_by_bot_id TEXT NOT NULL DEFAULT '',
                    device_code TEXT NOT NULL,
                    user_code TEXT NOT NULL DEFAULT '',
                    verification_url TEXT NOT NULL DEFAULT '',
                    qrcode_url TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL DEFAULT 5,
                    next_poll_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_baidu_oauth_sessions_status
                    ON baidu_oauth_sessions(status, created_at DESC);
                """
            )

    @staticmethod
    def _token_dict(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {
                "account_id": ACCOUNT_ID,
                "access_token": "",
                "refresh_token": "",
                "expires_at": None,
                "scope": "",
                "authorized_at": None,
                "updated_at": None,
            }
        return dict(row)

    def get_tokens(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM baidu_oauth_tokens WHERE account_id = ?",
                (ACCOUNT_ID,),
            ).fetchone()
            return self._token_dict(row)

    def save_tokens(
        self,
        *,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        scope: str = "",
    ) -> dict[str, Any]:
        now = utc_now_dt()
        expires_at = now + timedelta(seconds=max(60, int(expires_in or 0)))
        current = self.get_tokens()
        effective_refresh = str(refresh_token or current.get("refresh_token") or "").strip()
        authorized_at = str(current.get("authorized_at") or now.isoformat())
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO baidu_oauth_tokens (
                    account_id, access_token, refresh_token, expires_at,
                    scope, authorized_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    scope = excluded.scope,
                    authorized_at = excluded.authorized_at,
                    updated_at = excluded.updated_at
                """,
                (
                    ACCOUNT_ID,
                    str(access_token).strip(),
                    effective_refresh,
                    expires_at.isoformat(),
                    str(scope or current.get("scope") or ""),
                    authorized_at,
                    now.isoformat(),
                ),
            )
        return self.get_tokens()

    def clear_tokens(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM baidu_oauth_tokens WHERE account_id = ?", (ACCOUNT_ID,))
            connection.execute(
                "UPDATE baidu_oauth_sessions SET status = 'cancelled', updated_at = ? WHERE status = 'pending'",
                (utc_now(),),
            )

    @staticmethod
    def _session_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["interval_seconds"] = max(3, int(data.get("interval_seconds") or 5))
        return data

    def create_session(
        self,
        *,
        requested_by_bot_id: str,
        device_code: str,
        user_code: str,
        verification_url: str,
        qrcode_url: str,
        expires_in: int,
        interval_seconds: int,
    ) -> dict[str, Any]:
        now = utc_now_dt()
        interval = max(3, int(interval_seconds or 5))
        session_id = uuid.uuid4().hex
        expires_at = now + timedelta(seconds=max(60, int(expires_in or 0)))
        next_poll_at = now + timedelta(seconds=interval)
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE baidu_oauth_sessions SET status = 'superseded', updated_at = ? WHERE status = 'pending'",
                (now.isoformat(),),
            )
            connection.execute(
                """
                INSERT INTO baidu_oauth_sessions (
                    id, requested_by_bot_id, device_code, user_code,
                    verification_url, qrcode_url, expires_at,
                    interval_seconds, next_poll_at, status, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)
                """,
                (
                    session_id,
                    requested_by_bot_id,
                    device_code,
                    user_code,
                    verification_url,
                    qrcode_url,
                    expires_at.isoformat(),
                    interval,
                    next_poll_at.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("无法保存百度网盘授权会话")
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM baidu_oauth_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return self._session_dict(row)

    def latest_pending_session(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM baidu_oauth_sessions
                WHERE status = 'pending' AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (utc_now(),),
            ).fetchone()
            return self._session_dict(row)

    def claim_poll(self, session_id: str) -> bool:
        now = utc_now_dt()
        session = self.get_session(session_id)
        if session is None or session.get("status") != "pending":
            return False
        interval = max(3, int(session.get("interval_seconds") or 5))
        next_poll_at = now + timedelta(seconds=interval)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE baidu_oauth_sessions
                SET next_poll_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending' AND next_poll_at <= ?
                """,
                (next_poll_at.isoformat(), now.isoformat(), session_id, now.isoformat()),
            )
            return cursor.rowcount == 1

    def delay_poll(self, session_id: str, extra_seconds: int = 5) -> None:
        now = utc_now_dt()
        session = self.get_session(session_id)
        if session is None:
            return
        interval = max(3, int(session.get("interval_seconds") or 5) + max(1, int(extra_seconds)))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE baidu_oauth_sessions
                SET interval_seconds = ?, next_poll_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (interval, (now + timedelta(seconds=interval)).isoformat(), now.isoformat(), session_id),
            )

    def set_session_status(self, session_id: str, status: str, error: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE baidu_oauth_sessions
                SET status = ?, last_error = ?, updated_at = ? WHERE id = ?
                """,
                (status, str(error or "")[:1000], utc_now(), session_id),
            )


baidu_oauth_repository = BaiduOAuthRepository()
