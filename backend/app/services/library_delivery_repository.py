from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "library_delivery.db"
DEFAULT_LIBRARY_PATH = "/app/data/library.sqlite3"
DEFAULT_TABLE_NAME = "新网盘资料"
DEFAULT_API_URL = "https://pan.baidu.com/rest/2.0/xpan/share"
DEFAULT_API_METHOD = "set"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class LibraryDeliveryRepository:
    def __init__(self, path: Path = DATABASE_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS library_delivery_settings (
                    bot_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    database_path TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    title_column TEXT NOT NULL,
                    category_column TEXT NOT NULL,
                    size_column TEXT NOT NULL,
                    fsid_column TEXT NOT NULL,
                    path_column TEXT NOT NULL,
                    access_token TEXT NOT NULL DEFAULT '',
                    share_period INTEGER NOT NULL DEFAULT 7,
                    session_ttl_seconds INTEGER NOT NULL DEFAULT 180,
                    api_url TEXT NOT NULL,
                    api_method TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS library_search_sessions (
                    id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    query TEXT NOT NULL,
                    total_count INTEGER NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS library_processed_messages (
                    bot_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY(bot_id, message_id, action)
                );

                CREATE TABLE IF NOT EXISTS library_delivery_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    session_id TEXT,
                    group_openid TEXT NOT NULL DEFAULT '',
                    member_openid TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    query TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    fsid TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL,
                    status_code INTEGER,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_library_sessions_lookup
                    ON library_search_sessions(bot_id, group_openid, member_openid, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_library_logs_bot
                    ON library_delivery_logs(bot_id, created_at DESC);
                """
            )

    @staticmethod
    def _default_settings(bot_id: str) -> dict[str, Any]:
        return {
            "bot_id": bot_id,
            "enabled": False,
            "database_path": DEFAULT_LIBRARY_PATH,
            "table_name": DEFAULT_TABLE_NAME,
            "title_column": "标题",
            "category_column": "分类",
            "size_column": "大小",
            "fsid_column": "fsid",
            "path_column": "网盘地址",
            "access_token": "",
            "share_period": 7,
            "session_ttl_seconds": 180,
            "api_url": DEFAULT_API_URL,
            "api_method": DEFAULT_API_METHOD,
            "updated_at": None,
        }

    @classmethod
    def _settings_dict(cls, row: sqlite3.Row | None, bot_id: str) -> dict[str, Any]:
        if row is None:
            return cls._default_settings(bot_id)
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["share_period"] = int(data["share_period"])
        data["session_ttl_seconds"] = int(data["session_ttl_seconds"])
        return data

    def get_private_settings(self, bot_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_delivery_settings WHERE bot_id = ?",
                (bot_id,),
            ).fetchone()
            return self._settings_dict(row, bot_id)

    def get_public_settings(self, bot_id: str) -> dict[str, Any]:
        settings = self.get_private_settings(bot_id)
        token = str(settings.pop("access_token", "") or "")
        settings["access_token_configured"] = bool(token)
        return settings

    def update_settings(self, bot_id: str, **values: Any) -> dict[str, Any]:
        current = self.get_private_settings(bot_id)
        token = values.pop("access_token", None)
        clear_token = bool(values.pop("clear_access_token", False))
        current.update(values)
        if clear_token:
            current["access_token"] = ""
        elif token is not None and str(token).strip():
            current["access_token"] = str(token).strip()
        current["updated_at"] = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO library_delivery_settings (
                    bot_id, enabled, database_path, table_name, title_column,
                    category_column, size_column, fsid_column, path_column,
                    access_token, share_period, session_ttl_seconds,
                    api_url, api_method, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    database_path = excluded.database_path,
                    table_name = excluded.table_name,
                    title_column = excluded.title_column,
                    category_column = excluded.category_column,
                    size_column = excluded.size_column,
                    fsid_column = excluded.fsid_column,
                    path_column = excluded.path_column,
                    access_token = excluded.access_token,
                    share_period = excluded.share_period,
                    session_ttl_seconds = excluded.session_ttl_seconds,
                    api_url = excluded.api_url,
                    api_method = excluded.api_method,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id,
                    int(bool(current["enabled"])),
                    str(current["database_path"]),
                    str(current["table_name"]),
                    str(current["title_column"]),
                    str(current["category_column"]),
                    str(current["size_column"]),
                    str(current["fsid_column"]),
                    str(current["path_column"]),
                    str(current.get("access_token") or ""),
                    int(current["share_period"]),
                    int(current["session_ttl_seconds"]),
                    str(current["api_url"]),
                    str(current["api_method"]),
                    current["updated_at"],
                ),
            )
        return self.get_public_settings(bot_id)

    def create_session(
        self,
        *,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        query: str,
        total_count: int,
        results: list[dict[str, Any]],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        session_id = uuid.uuid4().hex
        expires_at = now + timedelta(seconds=max(30, int(ttl_seconds)))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE library_search_sessions
                SET consumed_at = COALESCE(consumed_at, ?)
                WHERE bot_id = ? AND group_openid = ? AND member_openid = ?
                  AND consumed_at IS NULL
                """,
                (now.isoformat(), bot_id, group_openid, member_openid),
            )
            connection.execute(
                """
                INSERT INTO library_search_sessions (
                    id, bot_id, group_openid, member_openid, query,
                    total_count, results_json, created_at, expires_at, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    session_id,
                    bot_id,
                    group_openid,
                    member_openid,
                    query,
                    int(total_count),
                    json.dumps(results, ensure_ascii=False),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("无法创建资料检索会话")
        return session

    @staticmethod
    def _session_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        try:
            decoded = json.loads(str(data.get("results_json") or "[]"))
        except ValueError:
            decoded = []
        data["results"] = decoded if isinstance(decoded, list) else []
        data.pop("results_json", None)
        expires_at = _parse_time(data.get("expires_at"))
        data["expired"] = bool(expires_at and expires_at <= datetime.now(timezone.utc))
        return data

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM library_search_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return self._session_dict(row)

    def get_active_session(self, bot_id: str, group_openid: str, member_openid: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM library_search_sessions
                WHERE bot_id = ? AND group_openid = ? AND member_openid = ?
                  AND consumed_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (bot_id, group_openid, member_openid, now),
            ).fetchone()
            return self._session_dict(row)

    def consume_session(self, session_id: str) -> bool:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE library_search_sessions SET consumed_at = ?
                WHERE id = ? AND consumed_at IS NULL AND expires_at > ?
                """,
                (now, session_id, now),
            )
            return cursor.rowcount == 1

    def claim_message(self, bot_id: str, message_id: str, action: str) -> bool:
        if not message_id:
            return True
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO library_processed_messages
                    (bot_id, message_id, action, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (bot_id, message_id, action, utc_now()),
            )
            return cursor.rowcount == 1

    def add_log(
        self,
        *,
        bot_id: str,
        action: str,
        success: bool,
        session_id: str | None = None,
        group_openid: str = "",
        member_openid: str = "",
        query: str = "",
        title: str = "",
        fsid: str = "",
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO library_delivery_logs (
                    bot_id, session_id, group_openid, member_openid,
                    action, query, title, fsid, success, status_code,
                    detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_id, session_id, group_openid, member_openid,
                    action, query, title, fsid, int(bool(success)),
                    status_code, detail[:2000], utc_now(),
                ),
            )

    def list_logs(self, bot_id: str, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM library_delivery_logs
                WHERE bot_id = ? ORDER BY id DESC LIMIT ?
                """,
                (bot_id, max(1, min(200, int(limit)))),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["success"] = bool(item["success"])
                result.append(item)
            return result

    def counts(self, bot_id: str) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            active = connection.execute(
                """
                SELECT COUNT(*) FROM library_search_sessions
                WHERE bot_id = ? AND consumed_at IS NULL AND expires_at > ?
                """,
                (bot_id, utc_now()),
            ).fetchone()[0]
            searches = connection.execute(
                "SELECT COUNT(*) FROM library_delivery_logs WHERE bot_id = ? AND action = 'search' AND success = 1",
                (bot_id,),
            ).fetchone()[0]
            delivered = connection.execute(
                "SELECT COUNT(*) FROM library_delivery_logs WHERE bot_id = ? AND action = 'share_created' AND success = 1",
                (bot_id,),
            ).fetchone()[0]
            failures = connection.execute(
                "SELECT COUNT(*) FROM library_delivery_logs WHERE bot_id = ? AND success = 0",
                (bot_id,),
            ).fetchone()[0]
            return {
                "active_sessions": int(active),
                "searches": int(searches),
                "delivered": int(delivered),
                "failures": int(failures),
            }


library_delivery_repository = LibraryDeliveryRepository()
