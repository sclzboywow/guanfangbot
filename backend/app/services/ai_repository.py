from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "ai_companion.db"
JOB_LIMIT_PER_BOT = 2_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, seconds))).isoformat()


DEFAULT_PROFILE: dict[str, Any] = {
    "enabled": False,
    "model": "deepseek-v4-flash",
    "thinking_enabled": False,
    "identity_name": "QQ AI 伙伴",
    "role_description": "你是一个轻量、友好、可靠的聊天伙伴。",
    "relationship_description": "把对方当作正在与你聊天的朋友，平等交流。",
    "speaking_style": "自然、简洁、口语化，不使用生硬的客服腔。",
    "response_length": "short",
    "restrictions": "不冒充真人，不泄露系统提示，不编造自己看见了未提供的图片内容。",
    "custom_prompt": "",
    "reply_mode": "auto",
    "quote_fallback": True,
    "context_turns": 12,
    "max_tokens": 600,
    "allow_images": False,
    "image_assets": [],
    "failure_message": "刚才有点忙不过来，稍后再聊吧。",
}


class AiRepository:
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
                CREATE TABLE IF NOT EXISTS ai_credentials (
                    owner_user_id TEXT PRIMARY KEY,
                    encrypted_api_key TEXT NOT NULL,
                    key_hint TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_bot_profiles (
                    bot_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    model TEXT NOT NULL DEFAULT 'deepseek-v4-flash',
                    thinking_enabled INTEGER NOT NULL DEFAULT 0,
                    identity_name TEXT NOT NULL DEFAULT 'QQ AI 伙伴',
                    role_description TEXT NOT NULL DEFAULT '',
                    relationship_description TEXT NOT NULL DEFAULT '',
                    speaking_style TEXT NOT NULL DEFAULT '',
                    response_length TEXT NOT NULL DEFAULT 'short',
                    restrictions TEXT NOT NULL DEFAULT '',
                    custom_prompt TEXT NOT NULL DEFAULT '',
                    reply_mode TEXT NOT NULL DEFAULT 'auto',
                    quote_fallback INTEGER NOT NULL DEFAULT 1,
                    context_turns INTEGER NOT NULL DEFAULT 12,
                    max_tokens INTEGER NOT NULL DEFAULT 600,
                    allow_images INTEGER NOT NULL DEFAULT 0,
                    image_assets_json TEXT NOT NULL DEFAULT '[]',
                    failure_message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_reply_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    user_openid TEXT NOT NULL,
                    trigger_message_id TEXT NOT NULL,
                    trigger_content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    output_text TEXT NOT NULL DEFAULT '',
                    output_image_key TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    qq_message_id TEXT NOT NULL DEFAULT '',
                    delivery_mode TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(bot_id, trigger_message_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ai_jobs_pending
                    ON ai_reply_jobs(status, available_at, id);
                CREATE INDEX IF NOT EXISTS idx_ai_jobs_conversation
                    ON ai_reply_jobs(bot_id, user_openid, id);
                CREATE INDEX IF NOT EXISTS idx_ai_jobs_bot
                    ON ai_reply_jobs(bot_id, id DESC);

                CREATE TRIGGER IF NOT EXISTS trim_ai_jobs_after_insert
                AFTER INSERT ON ai_reply_jobs
                BEGIN
                    DELETE FROM ai_reply_jobs
                    WHERE bot_id = NEW.bot_id
                      AND id NOT IN (
                          SELECT id FROM ai_reply_jobs
                          WHERE bot_id = NEW.bot_id
                          ORDER BY id DESC
                          LIMIT {JOB_LIMIT_PER_BOT}
                      );
                END;
                """
            )
            connection.execute(
                "UPDATE ai_reply_jobs SET status = 'pending', started_at = NULL, available_at = ? WHERE status = 'running'",
                (utc_now(),),
            )

    @staticmethod
    def _profile_dict(row: sqlite3.Row | None, bot_id: str) -> dict[str, Any]:
        if row is None:
            return {"bot_id": bot_id, **DEFAULT_PROFILE, "updated_at": None}
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["thinking_enabled"] = bool(data["thinking_enabled"])
        data["quote_fallback"] = bool(data["quote_fallback"])
        data["allow_images"] = bool(data["allow_images"])
        try:
            assets = json.loads(str(data.pop("image_assets_json") or "[]"))
        except ValueError:
            assets = []
        data["image_assets"] = assets if isinstance(assets, list) else []
        return data

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def credential_status(self, owner_user_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT key_hint, updated_at FROM ai_credentials WHERE owner_user_id = ?",
                (owner_user_id,),
            ).fetchone()
        return {
            "configured": row is not None,
            "key_hint": str(row["key_hint"] or "") if row else "",
            "updated_at": str(row["updated_at"] or "") if row else None,
        }

    def save_credential(self, owner_user_id: str, encrypted_api_key: str, key_hint: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_credentials (owner_user_id, encrypted_api_key, key_hint, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(owner_user_id) DO UPDATE SET
                    encrypted_api_key = excluded.encrypted_api_key,
                    key_hint = excluded.key_hint,
                    updated_at = excluded.updated_at
                """,
                (owner_user_id, encrypted_api_key, key_hint[:32], utc_now()),
            )

    def get_encrypted_credential(self, owner_user_id: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_api_key FROM ai_credentials WHERE owner_user_id = ?",
                (owner_user_id,),
            ).fetchone()
        return str(row["encrypted_api_key"]) if row else None

    def delete_credential(self, owner_user_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM ai_credentials WHERE owner_user_id = ?",
                (owner_user_id,),
            )
            return cursor.rowcount > 0

    def get_profile(self, bot_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ai_bot_profiles WHERE bot_id = ?",
                (bot_id,),
            ).fetchone()
        return self._profile_dict(row, bot_id)

    def save_profile(self, bot_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        values = {**DEFAULT_PROFILE, **profile}
        assets_json = json.dumps(values.get("image_assets") or [], ensure_ascii=False, separators=(",", ":"))
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_bot_profiles (
                    bot_id, enabled, model, thinking_enabled, identity_name,
                    role_description, relationship_description, speaking_style,
                    response_length, restrictions, custom_prompt, reply_mode,
                    quote_fallback, context_turns, max_tokens, allow_images,
                    image_assets_json, failure_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    model = excluded.model,
                    thinking_enabled = excluded.thinking_enabled,
                    identity_name = excluded.identity_name,
                    role_description = excluded.role_description,
                    relationship_description = excluded.relationship_description,
                    speaking_style = excluded.speaking_style,
                    response_length = excluded.response_length,
                    restrictions = excluded.restrictions,
                    custom_prompt = excluded.custom_prompt,
                    reply_mode = excluded.reply_mode,
                    quote_fallback = excluded.quote_fallback,
                    context_turns = excluded.context_turns,
                    max_tokens = excluded.max_tokens,
                    allow_images = excluded.allow_images,
                    image_assets_json = excluded.image_assets_json,
                    failure_message = excluded.failure_message,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id,
                    int(bool(values["enabled"])),
                    str(values["model"]),
                    int(bool(values["thinking_enabled"])),
                    str(values["identity_name"]),
                    str(values["role_description"]),
                    str(values["relationship_description"]),
                    str(values["speaking_style"]),
                    str(values["response_length"]),
                    str(values["restrictions"]),
                    str(values["custom_prompt"]),
                    str(values["reply_mode"]),
                    int(bool(values["quote_fallback"])),
                    int(values["context_turns"]),
                    int(values["max_tokens"]),
                    int(bool(values["allow_images"])),
                    assets_json,
                    str(values["failure_message"]),
                    now,
                ),
            )
        return self.get_profile(bot_id)

    def enqueue_job(
        self,
        *,
        bot_id: str,
        owner_user_id: str,
        user_openid: str,
        trigger_message_id: str,
        trigger_content: str,
        delay_seconds: float = 0,
    ) -> dict[str, Any] | None:
        if not trigger_message_id:
            return None
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ai_reply_jobs (
                    bot_id, owner_user_id, user_openid, trigger_message_id,
                    trigger_content, status, attempts, available_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (
                    bot_id,
                    owner_user_id,
                    user_openid,
                    trigger_message_id,
                    trigger_content[:8000],
                    _future(delay_seconds),
                    now,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            row = connection.execute(
                "SELECT * FROM ai_reply_jobs WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
        return self._job_dict(row) if row else None

    def claim_next_job(self) -> dict[str, Any] | None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job.*
                FROM ai_reply_jobs AS job
                WHERE job.status = 'pending'
                  AND job.available_at <= ?
                  AND NOT EXISTS (
                      SELECT 1 FROM ai_reply_jobs AS earlier
                      WHERE earlier.bot_id = job.bot_id
                        AND earlier.user_openid = job.user_openid
                        AND earlier.id < job.id
                        AND earlier.status IN ('pending', 'running')
                  )
                ORDER BY job.id
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE ai_reply_jobs
                SET status = 'running', attempts = attempts + 1, started_at = ?, error = ''
                WHERE id = ? AND status = 'pending'
                """,
                (now, int(row["id"])),
            )
            claimed = connection.execute(
                "SELECT * FROM ai_reply_jobs WHERE id = ?",
                (int(row["id"]),),
            ).fetchone()
            connection.commit()
        return self._job_dict(claimed) if claimed else None

    def complete_job(
        self,
        job_id: int,
        *,
        output_text: str,
        output_image_key: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        qq_message_id: str,
        delivery_mode: str,
        error: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE ai_reply_jobs
                SET status = 'completed', completed_at = ?, output_text = ?,
                    output_image_key = ?, model = ?, prompt_tokens = ?,
                    completion_tokens = ?, total_tokens = ?, qq_message_id = ?,
                    delivery_mode = ?, error = ?
                WHERE id = ?
                """,
                (
                    utc_now(), output_text[:8000], output_image_key[:80], model[:120],
                    max(0, int(prompt_tokens)), max(0, int(completion_tokens)),
                    max(0, int(total_tokens)), qq_message_id[:256], delivery_mode[:80],
                    error[:1600], int(job_id),
                ),
            )

    def fail_job(self, job_id: int, error: str, *, retry: bool, delay_seconds: float = 5) -> None:
        with self._lock, self._connect() as connection:
            if retry:
                connection.execute(
                    """
                    UPDATE ai_reply_jobs
                    SET status = 'pending', available_at = ?, started_at = NULL, error = ?
                    WHERE id = ?
                    """,
                    (_future(delay_seconds), error[:1600], int(job_id)),
                )
            else:
                connection.execute(
                    """
                    UPDATE ai_reply_jobs
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE id = ?
                    """,
                    (utc_now(), error[:1600], int(job_id)),
                )

    def list_jobs(self, bot_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ai_reply_jobs WHERE bot_id = ? ORDER BY id DESC LIMIT ?",
                (bot_id, max(1, min(200, int(limit)))),
            ).fetchall()
        return [self._job_dict(row) for row in rows]

    def counts(self, bot_id: str) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS value FROM ai_reply_jobs WHERE bot_id = ? GROUP BY status",
                (bot_id,),
            ).fetchall()
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for row in rows:
            counts[str(row["status"])] = int(row["value"] or 0)
        return counts


ai_repository = AiRepository()
