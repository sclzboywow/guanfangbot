from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "group_verification.db"
DEFAULT_SUCCESS_MESSAGE = "验证通过，你现在可以正常发言。"
DEFAULT_CUSTOM_QUESTION = "请回答本群的入群验证问题"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GroupVerificationRepository:
    """SQLite-backed verification settings, sessions, dedupe keys and action logs."""

    def __init__(self, path: Path = DATABASE_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _add_columns(connection: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in definitions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS verification_settings (
                    bot_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    math_enabled INTEGER NOT NULL DEFAULT 1,
                    custom_question_enabled INTEGER NOT NULL DEFAULT 0,
                    combination_mode TEXT NOT NULL DEFAULT 'all',
                    custom_question TEXT NOT NULL DEFAULT '请回答本群的入群验证问题',
                    custom_answers TEXT NOT NULL DEFAULT '[]',
                    custom_ignore_case INTEGER NOT NULL DEFAULT 1,
                    min_operand INTEGER NOT NULL DEFAULT 1,
                    max_operand INTEGER NOT NULL DEFAULT 20,
                    timeout_seconds INTEGER NOT NULL DEFAULT 180,
                    max_wrong_attempts INTEGER NOT NULL DEFAULT 3,
                    failure_mute_minutes INTEGER NOT NULL DEFAULT 1440,
                    success_message TEXT NOT NULL DEFAULT '验证通过，你现在可以正常发言。',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS verification_sessions (
                    id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    member_name TEXT NOT NULL DEFAULT '',
                    operand_a INTEGER NOT NULL DEFAULT 0,
                    operand_b INTEGER NOT NULL DEFAULT 0,
                    operator TEXT NOT NULL DEFAULT '',
                    answer INTEGER NOT NULL DEFAULT 0,
                    question TEXT NOT NULL,
                    challenge_type TEXT NOT NULL DEFAULT 'math',
                    accepted_answers TEXT NOT NULL DEFAULT '[]',
                    required_challenges TEXT NOT NULL DEFAULT '["math"]',
                    completed_challenges TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    deadline_at TEXT,
                    verified_at TEXT,
                    failed_at TEXT,
                    failure_reason TEXT NOT NULL DEFAULT '',
                    mute_expire_at TEXT,
                    muted_until TEXT,
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
            self._add_columns(connection, "verification_settings", {
                "success_message": "TEXT NOT NULL DEFAULT '验证通过，你现在可以正常发言。'",
                "math_enabled": "INTEGER NOT NULL DEFAULT 1",
                "custom_question_enabled": "INTEGER NOT NULL DEFAULT 0",
                "combination_mode": "TEXT NOT NULL DEFAULT 'all'",
                "custom_question": "TEXT NOT NULL DEFAULT '请回答本群的入群验证问题'",
                "custom_answers": "TEXT NOT NULL DEFAULT '[]'",
                "custom_ignore_case": "INTEGER NOT NULL DEFAULT 1",
                "timeout_seconds": "INTEGER NOT NULL DEFAULT 180",
                "max_wrong_attempts": "INTEGER NOT NULL DEFAULT 3",
                "failure_mute_minutes": "INTEGER NOT NULL DEFAULT 1440",
            })
            self._add_columns(connection, "verification_sessions", {
                "challenge_type": "TEXT NOT NULL DEFAULT 'math'",
                "accepted_answers": "TEXT NOT NULL DEFAULT '[]'",
                "required_challenges": "TEXT NOT NULL DEFAULT '[\"math\"]'",
                "completed_challenges": "TEXT NOT NULL DEFAULT '[]'",
                "deadline_at": "TEXT",
                "failed_at": "TEXT",
                "failure_reason": "TEXT NOT NULL DEFAULT ''",
                "mute_expire_at": "TEXT",
                "muted_until": "TEXT",
            })
            # Indexes that reference migrated columns must be created after ALTER TABLE.
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_verification_sessions_deadline
                    ON verification_sessions(status, deadline_at)
                """
            )

    @staticmethod
    def _json_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in ("accepted_answers", "required_challenges", "completed_challenges"):
            data[key] = cls._json_list(data.get(key))
        data["mute_expire_at"] = data.get("mute_expire_at") or data.get("muted_until")
        return data

    def get_settings(self, bot_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM verification_settings WHERE bot_id = ?", (bot_id,)
            ).fetchone()
        if row is None:
            return {
                "bot_id": bot_id,
                "enabled": False,
                "math_enabled": True,
                "custom_question_enabled": False,
                "combination_mode": "all",
                "custom_question": DEFAULT_CUSTOM_QUESTION,
                "custom_answers": [],
                "custom_ignore_case": True,
                "min_operand": 1,
                "max_operand": 20,
                "timeout_seconds": 180,
                "max_wrong_attempts": 3,
                "failure_mute_minutes": 1440,
                "success_message": DEFAULT_SUCCESS_MESSAGE,
                "updated_at": None,
            }
        result = dict(row)
        for key in ("enabled", "math_enabled", "custom_question_enabled", "custom_ignore_case"):
            result[key] = bool(result[key])
        result["custom_answers"] = self._json_list(result.get("custom_answers"))
        return result

    def update_settings(
        self,
        bot_id: str,
        *,
        enabled: bool,
        min_operand: int,
        max_operand: int,
        success_message: str = DEFAULT_SUCCESS_MESSAGE,
        math_enabled: bool = True,
        custom_question_enabled: bool = False,
        combination_mode: str = "all",
        custom_question: str = DEFAULT_CUSTOM_QUESTION,
        custom_answers: list[str] | None = None,
        custom_ignore_case: bool = True,
        timeout_seconds: int = 180,
        max_wrong_attempts: int = 3,
        failure_mute_minutes: int = 1440,
    ) -> dict[str, Any]:
        updated_at = utc_now()
        answers = list(dict.fromkeys(str(item).strip() for item in (custom_answers or []) if str(item).strip()))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO verification_settings(
                    bot_id, enabled, math_enabled, custom_question_enabled, combination_mode,
                    custom_question, custom_answers, custom_ignore_case, min_operand,
                    max_operand, timeout_seconds, max_wrong_attempts, failure_mute_minutes,
                    success_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    enabled=excluded.enabled, math_enabled=excluded.math_enabled,
                    custom_question_enabled=excluded.custom_question_enabled,
                    combination_mode=excluded.combination_mode,
                    custom_question=excluded.custom_question,
                    custom_answers=excluded.custom_answers,
                    custom_ignore_case=excluded.custom_ignore_case,
                    min_operand=excluded.min_operand, max_operand=excluded.max_operand,
                    timeout_seconds=excluded.timeout_seconds,
                    max_wrong_attempts=excluded.max_wrong_attempts,
                    failure_mute_minutes=excluded.failure_mute_minutes,
                    success_message=excluded.success_message, updated_at=excluded.updated_at
                """,
                (
                    bot_id, int(enabled), int(math_enabled), int(custom_question_enabled),
                    combination_mode, custom_question, json.dumps(answers, ensure_ascii=False),
                    int(custom_ignore_case), min_operand, max_operand, timeout_seconds,
                    max_wrong_attempts, failure_mute_minutes, success_message, updated_at,
                ),
            )
        return self.get_settings(bot_id)

    def create_or_reset_session(
        self,
        *,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        member_name: str,
        operand_a: int = 0,
        operand_b: int = 0,
        operator: str = "",
        answer: int = 0,
        question: str,
        challenge_type: str = "math",
        accepted_answers: list[str] | None = None,
        required_challenges: list[str] | None = None,
        completed_challenges: list[str] | None = None,
        joined_at: str | None = None,
        deadline_at: str | None = None,
    ) -> dict[str, Any]:
        session_id = f"verify-{uuid.uuid4().hex[:16]}"
        joined_at = joined_at or utc_now()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM verification_sessions WHERE bot_id=? AND group_openid=? AND member_openid=?",
                (bot_id, group_openid, member_openid),
            ).fetchone()
            if existing:
                session_id = str(existing["id"])
            connection.execute(
                """
                INSERT INTO verification_sessions(
                    id, bot_id, group_openid, member_openid, member_name,
                    operand_a, operand_b, operator, answer, question, challenge_type,
                    accepted_answers, required_challenges, completed_challenges, status,
                    joined_at, deadline_at, verified_at, failed_at, failure_reason,
                    mute_expire_at, removed_at, wrong_attempts, retracted_messages,
                    last_message_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?,
                          NULL, NULL, '', NULL, NULL, 0, 0, NULL, '')
                ON CONFLICT(bot_id, group_openid, member_openid) DO UPDATE SET
                    member_name=CASE WHEN excluded.member_name!='' THEN excluded.member_name ELSE verification_sessions.member_name END,
                    operand_a=excluded.operand_a, operand_b=excluded.operand_b,
                    operator=excluded.operator, answer=excluded.answer, question=excluded.question,
                    challenge_type=excluded.challenge_type, accepted_answers=excluded.accepted_answers,
                    required_challenges=excluded.required_challenges,
                    completed_challenges=excluded.completed_challenges, status='pending',
                    joined_at=excluded.joined_at, deadline_at=excluded.deadline_at,
                    verified_at=NULL, failed_at=NULL, failure_reason='', mute_expire_at=NULL,
                    muted_until=NULL,
                    removed_at=NULL, wrong_attempts=0, retracted_messages=0,
                    last_message_at=NULL, last_error=''
                """,
                (
                    session_id, bot_id, group_openid, member_openid, member_name,
                    operand_a, operand_b, operator, answer, question, challenge_type,
                    json.dumps(accepted_answers or [], ensure_ascii=False),
                    json.dumps(required_challenges or [challenge_type], ensure_ascii=False),
                    json.dumps(completed_challenges or [], ensure_ascii=False),
                    joined_at, deadline_at,
                ),
            )
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("无法创建验证会话")
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM verification_sessions WHERE id=?", (session_id,)).fetchone()
        return self._row_to_dict(row)

    def get_pending_session(self, bot_id: str, group_openid: str, member_openid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM verification_sessions WHERE bot_id=? AND group_openid=? AND member_openid=? AND status='pending'",
                (bot_id, group_openid, member_openid),
            ).fetchone()
        return self._row_to_dict(row)

    def list_sessions(self, bot_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM verification_sessions WHERE bot_id=?
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'failed' THEN 1 WHEN 'verified' THEN 2 ELSE 3 END,
                         joined_at DESC LIMIT ?""",
                (bot_id, limit),
            ).fetchall()
        return [self._row_to_dict(row) or {} for row in rows]

    def list_expired_pending(self, now: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM verification_sessions
                WHERE status='pending' AND deadline_at IS NOT NULL AND deadline_at<=?
                ORDER BY deadline_at LIMIT ?""",
                (now or utc_now(), limit),
            ).fetchall()
        return [self._row_to_dict(row) or {} for row in rows]

    def list_logs(self, bot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM verification_logs WHERE bot_id=? ORDER BY id DESC LIMIT ?",
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
                "INSERT OR IGNORE INTO verification_processed_messages(message_id, bot_id, processed_at, action) VALUES (?, ?, ?, ?)",
                (message_id, bot_id, utc_now(), action),
            )
            return cursor.rowcount == 1

    def update_member_name(self, session_id: str, member_name: str) -> None:
        cleaned = str(member_name or "").strip()
        if not cleaned:
            return
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE verification_sessions SET member_name=? WHERE id=? AND (member_name='' OR member_name IS NULL)",
                (cleaned, session_id),
            )

    def mark_verified(self, session_id: str, *, verified_at: str | None = None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE verification_sessions SET status='verified', verified_at=?, deadline_at=NULL,
                mute_expire_at=NULL, muted_until=NULL, last_error='' WHERE id=?""",
                (verified_at or utc_now(), session_id),
            )

    def mark_failed(self, session_id: str, *, reason: str, mute_expire_at: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE verification_sessions SET status='failed', failed_at=?, failure_reason=?,
                mute_expire_at=?, muted_until=?, deadline_at=NULL WHERE id=? AND status='pending'""",
                (utc_now(), reason, mute_expire_at, mute_expire_at, session_id),
            )
            return cursor.rowcount == 1

    def restore_pending_after_mute_error(self, session_id: str, deadline_at: str | None) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE verification_sessions SET status='pending', failed_at=NULL,
                failure_reason='', mute_expire_at=NULL, muted_until=NULL, deadline_at=?,
                last_error='QQ官方禁言失败，将继续重试' WHERE id=? AND status='failed'""",
                (deadline_at or utc_now(), session_id),
            )

    def mark_removed(self, bot_id: str, group_openid: str, member_openid: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE verification_sessions SET status='removed', removed_at=?, deadline_at=NULL, last_error=''
                WHERE bot_id=? AND group_openid=? AND member_openid=? AND status!='removed'""",
                (utc_now(), bot_id, group_openid, member_openid),
            )

    def close_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE verification_sessions SET status='removed', removed_at=?, deadline_at=NULL WHERE id=?",
                (utc_now(), session_id),
            )

    def replace_problem(
        self,
        session_id: str,
        *,
        operand_a: int = 0,
        operand_b: int = 0,
        operator: str = "",
        answer: int = 0,
        question: str,
        challenge_type: str = "math",
        accepted_answers: list[str] | None = None,
        required_challenges: list[str] | None = None,
        completed_challenges: list[str] | None = None,
        deadline_at: str | None = None,
        reset_attempts: bool = True,
    ) -> dict[str, Any] | None:
        attempts_sql = "wrong_attempts=0, retracted_messages=0," if reset_attempts else ""
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""UPDATE verification_sessions SET operand_a=?, operand_b=?, operator=?, answer=?,
                question=?, challenge_type=?, accepted_answers=?, required_challenges=?, completed_challenges=?,
                deadline_at=?, status='pending', verified_at=NULL, failed_at=NULL, failure_reason='',
                mute_expire_at=NULL, muted_until=NULL, removed_at=NULL, {attempts_sql} last_error='' WHERE id=?""",
                (
                    operand_a, operand_b, operator, answer, question, challenge_type,
                    json.dumps(accepted_answers or [], ensure_ascii=False),
                    json.dumps(required_challenges or [challenge_type], ensure_ascii=False),
                    json.dumps(completed_challenges or [], ensure_ascii=False), deadline_at, session_id,
                ),
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
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """UPDATE verification_sessions SET wrong_attempts=wrong_attempts+1,
                retracted_messages=retracted_messages+?, last_message_at=?, last_error=? WHERE id=?""",
                (int(retracted), received_at or utc_now(), "" if retracted else detail[:500], session_id),
            )
            connection.execute(
                """INSERT INTO verification_logs(bot_id, session_id, action, success, status_code, detail, created_at)
                SELECT bot_id, id, 'retract_message', ?, ?, ?, ? FROM verification_sessions WHERE id=?""",
                (int(retracted), status_code, detail[:1000], utc_now(), session_id),
            )
        return self.get_session(session_id)

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
                "INSERT INTO verification_logs(bot_id, session_id, action, success, status_code, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            "failed": values.get("failed", 0),
            "removed": values.get("removed", 0),
            "total": sum(values.values()),
        }


group_verification_repository = GroupVerificationRepository()
