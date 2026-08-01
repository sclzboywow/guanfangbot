from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "group_verification.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GroupVerificationRepository:
    """SQLite-backed verification settings, sessions, dedupe keys and action logs."""

    def __init__(self, path: Path = DATABASE_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS verification_settings (
                    bot_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    min_operand INTEGER NOT NULL DEFAULT 1,
                    max_operand INTEGER NOT NULL DEFAULT 20,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS verification_sessions (
                    id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    member_name TEXT NOT NULL DEFAULT '',
                    operand_a INTEGER NOT NULL,
                    operand_b INTEGER NOT NULL,
                    operator TEXT NOT NULL,
                    answer INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    verified_at TEXT,
                    removed_at TEXT,
                    wrong_attempts INTEGER NOT NULL DEFAULT 0,
                    retracted_messages INTEGER NOT NULL DEFAULT 0,
                    last_message_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    UNIQUE(bot_id, group_openid, member_openid)
                );

                CREATE INDEX IF NOT EXISTS idx_verification_sessions_bot_status
                    ON verification_sessions(bot_id, status, joined_at DESC);

                CREATE TABLE IF NOT EXISTS verification_processed_messages (
                    message_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    PRIMARY KEY(message_id, bot_id)
                );

                CREATE TABLE IF NOT EXISTS verification_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    session_id TEXT,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    status_code INTEGER,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_verification_logs_bot_created
                    ON verification_logs(bot_id, created_at DESC);
                """
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get_settings(self, bot_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM verification_settings WHERE bot_id = ?", (bot_id,)
            ).fetchone()
        if row is None:
            return {
                "bot_id": bot_id,
                "enabled": False,
                "min_operand": 1,
                "max_operand": 20,
                "updated_at": None,
            }
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        return result

    def update_settings(self, bot_id: str, *, enabled: bool, min_operand: int, max_operand: int) -> dict[str, Any]:
        updated_at = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO verification_settings(bot_id, enabled, min_operand, max_operand, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    min_operand = excluded.min_operand,
                    max_operand = excluded.max_operand,
                    updated_at = excluded.updated_at
                """,
                (bot_id, int(enabled), min_operand, max_operand, updated_at),
            )
        return self.get_settings(bot_id)

    def create_or_reset_session(
        self,
        *,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        member_name: str,
        operand_a: int,
        operand_b: int,
        operator: str,
        answer: int,
        question: str,
        joined_at: str | None = None,
    ) -> dict[str, Any]:
        session_id = f"verify-{uuid.uuid4().hex[:16]}"
        joined_at = joined_at or utc_now()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """SELECT id FROM verification_sessions
                WHERE bot_id = ? AND group_openid = ? AND member_openid = ?""",
                (bot_id, group_openid, member_openid),
            ).fetchone()
            if existing:
                session_id = str(existing["id"])
            connection.execute(
                """
                INSERT INTO verification_sessions(
                    id, bot_id, group_openid, member_openid, member_name,
                    operand_a, operand_b, operator, answer, question, status,
                    joined_at, verified_at, removed_at, wrong_attempts,
                    retracted_messages, last_message_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, 0, 0, NULL, '')
                ON CONFLICT(bot_id, group_openid, member_openid) DO UPDATE SET
                    member_name = excluded.member_name,
                    operand_a = excluded.operand_a,
                    operand_b = excluded.operand_b,
                    operator = excluded.operator,
                    answer = excluded.answer,
                    question = excluded.question,
                    status = 'pending',
                    joined_at = excluded.joined_at,
                    verified_at = NULL,
                    removed_at = NULL,
                    wrong_attempts = 0,
                    retracted_messages = 0,
                    last_message_at = NULL,
                    last_error = ''
                """,
                (
                    session_id,
                    bot_id,
                    group_openid,
                    member_openid,
                    member_name,
                    operand_a,
                    operand_b,
                    operator,
                    answer,
                    question,
                    joined_at,
                ),
            )
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("无法创建验证会话")
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM verification_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._row_to_dict(row)

    def get_pending_session(self, bot_id: str, group_openid: str, member_openid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM verification_sessions
                WHERE bot_id = ? AND group_openid = ? AND member_openid = ? AND status = 'pending'
                """,
                (bot_id, group_openid, member_openid),
            ).fetchone()
        return self._row_to_dict(row)

    def list_sessions(self, bot_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM verification_sessions
                WHERE bot_id = ?
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'verified' THEN 1 ELSE 2 END,
                         joined_at DESC
                LIMIT ?
                """,
                (bot_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_logs(self, bot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM verification_logs WHERE bot_id = ? ORDER BY id DESC LIMIT ?",
                (bot_id, limit),
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["success"] = bool(item["success"])
        return result

    def claim_message(self, bot_id: str, message_id: str, action: str) -> bool:
        if not message_id:
            return True
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO verification_processed_messages(message_id, bot_id, processed_at, action)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, bot_id, utc_now(), action),
            )
            return cursor.rowcount == 1

    def mark_verified(self, session_id: str, *, verified_at: str | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE verification_sessions SET status='verified', verified_at=?, last_error='' WHERE id=?",
                (verified_at or utc_now(), session_id),
            )

    def mark_removed(self, bot_id: str, group_openid: str, member_openid: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE verification_sessions SET status='removed', removed_at=?, last_error=''
                WHERE bot_id=? AND group_openid=? AND member_openid=? AND status!='removed'
                """,
                (utc_now(), bot_id, group_openid, member_openid),
            )

    def close_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE verification_sessions SET status='removed', removed_at=? WHERE id=?",
                (utc_now(), session_id),
            )

    def replace_problem(
        self,
        session_id: str,
        *,
        operand_a: int,
        operand_b: int,
        operator: str,
        answer: int,
        question: str,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE verification_sessions SET
                    operand_a=?, operand_b=?, operator=?, answer=?, question=?,
                    status='pending', verified_at=NULL, removed_at=NULL,
                    wrong_attempts=0, retracted_messages=0, last_error=''
                WHERE id=?
                """,
                (operand_a, operand_b, operator, answer, question, session_id),
            )
        return self.get_session(session_id)

    def record_wrong_message(
        self,
        session_id: str,
        *,
        retracted: bool,
        status_code: int | None,
        detail: str,
        received_at: str | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE verification_sessions SET
                    wrong_attempts = wrong_attempts + 1,
                    retracted_messages = retracted_messages + ?,
                    last_message_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (int(retracted), received_at or utc_now(), "" if retracted else detail[:500], session_id),
            )
            connection.execute(
                """
                INSERT INTO verification_logs(bot_id, session_id, action, success, status_code, detail, created_at)
                SELECT bot_id, id, 'retract_message', ?, ?, ?, ? FROM verification_sessions WHERE id=?
                """,
                (int(retracted), status_code, detail[:1000], utc_now(), session_id),
            )

    def add_log(
        self,
        *,
        bot_id: str,
        session_id: str | None,
        action: str,
        success: bool,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO verification_logs(bot_id, session_id, action, success, status_code, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (bot_id, session_id, action, int(success), status_code, detail[:1000], utc_now()),
            )

    def counts(self, bot_id: str) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM verification_sessions WHERE bot_id=? GROUP BY status",
                (bot_id,),
            ).fetchall()
        values = {str(row["status"]): int(row["total"]) for row in rows}
        return {
            "pending": values.get("pending", 0),
            "verified": values.get("verified", 0),
            "removed": values.get("removed", 0),
            "total": sum(values.values()),
        }


group_verification_repository = GroupVerificationRepository()
