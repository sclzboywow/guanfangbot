from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "chat.db"
MESSAGE_LIMIT_PER_BOT = 10_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatRepository:
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
                f"""
                CREATE TABLE IF NOT EXISTS chat_contacts (
                    bot_id TEXT NOT NULL,
                    user_openid TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    accepts_messages INTEGER NOT NULL DEFAULT 1,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    last_message_at TEXT,
                    last_message_preview TEXT NOT NULL DEFAULT '',
                    last_inbound_msg_id TEXT NOT NULL DEFAULT '',
                    last_inbound_at TEXT,
                    last_event_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(bot_id, user_openid)
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    user_openid TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'text',
                    qq_message_id TEXT NOT NULL DEFAULT '',
                    event_id TEXT NOT NULL DEFAULT '',
                    reply_to_msg_id TEXT NOT NULL DEFAULT '',
                    msg_seq INTEGER,
                    content TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL DEFAULT 1,
                    status_code INTEGER,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chat_contacts_bot
                    ON chat_contacts(bot_id, active DESC, last_message_at DESC);
                CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
                    ON chat_messages(bot_id, user_openid, id DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_qq_dedupe
                    ON chat_messages(bot_id, qq_message_id, direction)
                    WHERE qq_message_id != '';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_event_dedupe
                    ON chat_messages(bot_id, event_id, kind)
                    WHERE event_id != '' AND kind = 'event';

                CREATE TRIGGER IF NOT EXISTS trim_chat_messages_after_insert
                AFTER INSERT ON chat_messages
                BEGIN
                    DELETE FROM chat_messages
                    WHERE bot_id = NEW.bot_id
                      AND id NOT IN (
                          SELECT id FROM chat_messages
                          WHERE bot_id = NEW.bot_id
                          ORDER BY id DESC
                          LIMIT {MESSAGE_LIMIT_PER_BOT}
                      );
                END;
                """
            )
            connection.execute(
                """
                DELETE FROM chat_messages
                WHERE id IN (
                    SELECT old.id
                    FROM chat_messages AS old
                    WHERE (
                        SELECT COUNT(*) FROM chat_messages AS newer
                        WHERE newer.bot_id = old.bot_id AND newer.id > old.id
                    ) >= ?
                )
                """,
                (MESSAGE_LIMIT_PER_BOT,),
            )

    @staticmethod
    def _contact_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["active"] = bool(data["active"])
        data["accepts_messages"] = bool(data["accepts_messages"])
        data["unread_count"] = int(data["unread_count"] or 0)
        return data

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["success"] = bool(data["success"])
        return data

    def get_contact(self, bot_id: str, user_openid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chat_contacts WHERE bot_id = ? AND user_openid = ?",
                (bot_id, user_openid),
            ).fetchone()
            return self._contact_dict(row)

    def set_display_name(self, bot_id: str, user_openid: str, display_name: str) -> dict[str, Any] | None:
        cleaned = " ".join(str(display_name or "").split()).strip()[:80]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_contacts
                SET display_name = ?, updated_at = ?
                WHERE bot_id = ? AND user_openid = ?
                """,
                (cleaned, utc_now(), bot_id, user_openid),
            )
            if cursor.rowcount <= 0:
                return None
        return self.get_contact(bot_id, user_openid)

    def list_contacts(self, bot_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM chat_contacts
                WHERE bot_id = ?
                ORDER BY active DESC, COALESCE(last_message_at, updated_at) DESC
                LIMIT ?
                """,
                (bot_id, max(1, min(1000, int(limit)))),
            ).fetchall()
            return [self._contact_dict(row) or {} for row in rows]

    def record_inbound(
        self,
        *,
        bot_id: str,
        user_openid: str,
        content: str,
        qq_message_id: str,
        event_id: str = "",
        display_name: str = "",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now()
        preview = " ".join(str(content or "").split())[:160]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO chat_messages (
                    bot_id, user_openid, direction, kind, qq_message_id,
                    event_id, content, success, created_at
                ) VALUES (?, ?, 'inbound', 'text', ?, ?, ?, 1, ?)
                """,
                (bot_id, user_openid, qq_message_id, event_id, str(content or ""), now),
            )
            unread_increment = 1 if cursor.rowcount == 1 else 0
            connection.execute(
                """
                INSERT INTO chat_contacts (
                    bot_id, user_openid, display_name, active, accepts_messages,
                    unread_count, last_message_at, last_message_preview,
                    last_inbound_msg_id, last_inbound_at, last_event_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, user_openid) DO UPDATE SET
                    display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE chat_contacts.display_name END,
                    active = 1,
                    accepts_messages = 1,
                    unread_count = chat_contacts.unread_count + excluded.unread_count,
                    last_message_at = excluded.last_message_at,
                    last_message_preview = excluded.last_message_preview,
                    last_inbound_msg_id = excluded.last_inbound_msg_id,
                    last_inbound_at = excluded.last_inbound_at,
                    last_event_id = CASE WHEN excluded.last_event_id != '' THEN excluded.last_event_id ELSE chat_contacts.last_event_id END,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id, user_openid, display_name.strip(), unread_increment,
                    now, preview, qq_message_id, now, event_id, now, now,
                ),
            )
        contact = self.get_contact(bot_id, user_openid)
        if contact is None:
            raise RuntimeError("无法保存单聊联系人")
        return contact

    def record_relation_event(
        self,
        *,
        bot_id: str,
        user_openid: str,
        event_type: str,
        event_id: str = "",
        display_name: str = "",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now()
        event_map = {
            "FRIEND_ADD": (True, True, "用户已添加机器人好友"),
            "FRIEND_DEL": (False, False, "用户已删除机器人好友"),
            "C2C_MSG_REJECT": (True, False, "用户已关闭机器人主动消息"),
            "C2C_MSG_RECEIVE": (True, True, "用户已允许机器人主动消息"),
        }
        active, accepts_messages, text = event_map[event_type]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO chat_messages (
                    bot_id, user_openid, direction, kind, event_id,
                    content, success, created_at
                ) VALUES (?, ?, 'system', 'event', ?, ?, 1, ?)
                """,
                (bot_id, user_openid, event_id, text, now),
            )
            if cursor.rowcount == 1:
                preview = text
                last_message_at: str | None = now
            else:
                preview = ""
                last_message_at = None
            connection.execute(
                """
                INSERT INTO chat_contacts (
                    bot_id, user_openid, display_name, active, accepts_messages,
                    unread_count, last_message_at, last_message_preview,
                    last_event_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, user_openid) DO UPDATE SET
                    display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE chat_contacts.display_name END,
                    active = excluded.active,
                    accepts_messages = excluded.accepts_messages,
                    last_message_at = COALESCE(excluded.last_message_at, chat_contacts.last_message_at),
                    last_message_preview = CASE WHEN excluded.last_message_preview != '' THEN excluded.last_message_preview ELSE chat_contacts.last_message_preview END,
                    last_event_id = CASE WHEN excluded.last_event_id != '' THEN excluded.last_event_id ELSE chat_contacts.last_event_id END,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id, user_openid, display_name.strip(), int(active), int(accepts_messages),
                    last_message_at, preview, event_id, now, now,
                ),
            )
        contact = self.get_contact(bot_id, user_openid)
        if contact is None:
            raise RuntimeError("无法保存好友关系事件")
        return contact

    def record_outbound(
        self,
        *,
        bot_id: str,
        user_openid: str,
        content: str,
        success: bool,
        kind: str = "text",
        qq_message_id: str = "",
        reply_to_msg_id: str = "",
        msg_seq: int | None = None,
        status_code: int | None = None,
        detail: str = "",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        now = created_at or utc_now()
        safe_kind = kind if kind in {"text", "image", "file", "audio", "video"} else "text"
        preview = " ".join(str(content or "").split())[:160]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO chat_messages (
                    bot_id, user_openid, direction, kind, qq_message_id,
                    reply_to_msg_id, msg_seq, content, success, status_code,
                    detail, created_at
                ) VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_id, user_openid, safe_kind, qq_message_id, reply_to_msg_id, msg_seq,
                    str(content or ""), int(success), status_code, detail[:1200], now,
                ),
            )
            message_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO chat_contacts (
                    bot_id, user_openid, active, accepts_messages, unread_count,
                    last_message_at, last_message_preview, created_at, updated_at
                ) VALUES (?, ?, 1, 1, 0, ?, ?, ?, ?)
                ON CONFLICT(bot_id, user_openid) DO UPDATE SET
                    last_message_at = excluded.last_message_at,
                    last_message_preview = excluded.last_message_preview,
                    updated_at = excluded.updated_at
                """,
                (bot_id, user_openid, now, preview, now, now),
            )
            row = connection.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
        if row is None:
            raise RuntimeError("无法保存发送消息")
        return self._message_dict(row)

    def list_messages(
        self,
        bot_id: str,
        user_openid: str,
        *,
        limit: int = 100,
        before_id: int | None = None,
        mark_read: bool = True,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(200, int(limit)))
        with self._lock, self._connect() as connection:
            if before_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM chat_messages
                    WHERE bot_id = ? AND user_openid = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (bot_id, user_openid, bounded_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM chat_messages
                    WHERE bot_id = ? AND user_openid = ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (bot_id, user_openid, before_id, bounded_limit),
                ).fetchall()
            if mark_read:
                connection.execute(
                    "UPDATE chat_contacts SET unread_count = 0, updated_at = ? WHERE bot_id = ? AND user_openid = ?",
                    (utc_now(), bot_id, user_openid),
                )
        return [self._message_dict(row) for row in reversed(rows)]

    def list_ai_context(self, bot_id: str, user_openid: str, *, turns: int = 12) -> list[dict[str, str]]:
        """Return recent successful text messages in chronological model format."""
        limit = max(2, min(60, int(turns) * 2))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT direction, content
                FROM chat_messages
                WHERE bot_id = ? AND user_openid = ?
                  AND kind = 'text' AND success = 1
                  AND direction IN ('inbound', 'outbound')
                  AND TRIM(content) != ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (bot_id, user_openid, limit),
            ).fetchall()
        result: list[dict[str, str]] = []
        for row in reversed(rows):
            role = "user" if row["direction"] == "inbound" else "assistant"
            result.append({"role": role, "content": str(row["content"])})
        return result

    def latest_reply_context(self, bot_id: str, user_openid: str) -> dict[str, Any] | None:
        contact = self.get_contact(bot_id, user_openid)
        if contact is None:
            return None
        return {
            "msg_id": str(contact.get("last_inbound_msg_id") or ""),
            "received_at": contact.get("last_inbound_at"),
            "event_id": str(contact.get("last_event_id") or ""),
        }

    def next_reply_seq(self, bot_id: str, reply_to_msg_id: str) -> int:
        if not reply_to_msg_id:
            return 1
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(msg_seq), 0) AS value FROM chat_messages
                WHERE bot_id = ? AND reply_to_msg_id = ?
                """,
                (bot_id, reply_to_msg_id),
            ).fetchone()
            return int(row["value"] or 0) + 1

    def counts(self, bot_id: str) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active,
                    SUM(unread_count) AS unread
                FROM chat_contacts WHERE bot_id = ?
                """,
                (bot_id,),
            ).fetchone()
            message_count = connection.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE bot_id = ?",
                (bot_id,),
            ).fetchone()[0]
        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "unread": int(row["unread"] or 0),
            "messages": int(message_count or 0),
        }


chat_repository = ChatRepository()
