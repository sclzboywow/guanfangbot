from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "group_management.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GroupManagementRepository:
    """Local cache and audit log for QQ's official group-management APIs."""

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
                CREATE TABLE IF NOT EXISTS managed_groups (
                    bot_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    group_id TEXT NOT NULL DEFAULT '',
                    group_name TEXT NOT NULL DEFAULT '',
                    group_finger_memo TEXT NOT NULL DEFAULT '',
                    group_class_text TEXT NOT NULL DEFAULT '',
                    group_tags TEXT NOT NULL DEFAULT '[]',
                    group_member_num INTEGER,
                    source TEXT NOT NULL DEFAULT 'event',
                    info_synced_at TEXT,
                    info_sync_error TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY(bot_id, group_openid)
                );

                CREATE TABLE IF NOT EXISTS group_management_settings (
                    bot_id TEXT PRIMARY KEY,
                    manual_approval_enabled INTEGER NOT NULL DEFAULT 1,
                    auto_approval_enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS official_join_requests (
                    bot_id TEXT NOT NULL,
                    join_request_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    union_openid TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    risk_tips TEXT NOT NULL DEFAULT '',
                    apply_at TEXT NOT NULL DEFAULT '',
                    apply_source TEXT NOT NULL DEFAULT '',
                    invited_by TEXT NOT NULL DEFAULT '',
                    is_bot INTEGER NOT NULL DEFAULT 0,
                    verify_info TEXT NOT NULL DEFAULT '{}',
                    auto_strategy_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    decision TEXT NOT NULL DEFAULT '',
                    decision_detail TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    decided_at TEXT,
                    PRIMARY KEY(bot_id, join_request_id)
                );

                CREATE TABLE IF NOT EXISTS group_management_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    group_openid TEXT NOT NULL DEFAULT '',
                    member_openid TEXT NOT NULL DEFAULT '',
                    strategy_id TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL,
                    status_code INTEGER,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_managed_groups_bot
                    ON managed_groups(bot_id, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_join_requests_bot_status
                    ON official_join_requests(bot_id, status, apply_at DESC);
                CREATE INDEX IF NOT EXISTS idx_group_management_logs_bot
                    ON group_management_logs(bot_id, created_at DESC);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(managed_groups)").fetchall()
            }
            for name, definition in {
                "group_id": "TEXT NOT NULL DEFAULT ''",
                "group_finger_memo": "TEXT NOT NULL DEFAULT ''",
                "group_class_text": "TEXT NOT NULL DEFAULT ''",
                "group_tags": "TEXT NOT NULL DEFAULT '[]'",
                "group_member_num": "INTEGER",
                "info_synced_at": "TEXT",
                "info_sync_error": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE managed_groups ADD COLUMN {name} {definition}")

    def remember_group(
        self,
        bot_id: str,
        group_openid: str,
        *,
        group_id: str = "",
        group_name: str = "",
        group_finger_memo: str = "",
        group_class_text: str = "",
        group_tags: list[str] | None = None,
        group_member_num: int | None = None,
        source: str = "event",
        info_synced: bool = False,
        info_sync_error: str = "",
    ) -> bool:
        cleaned = str(group_openid or "").strip()
        if not cleaned:
            return False
        with self._lock, self._connect() as connection:
            existed = connection.execute(
                "SELECT 1 FROM managed_groups WHERE bot_id=? AND group_openid=?",
                (bot_id, cleaned),
            ).fetchone() is not None
            connection.execute(
                """
                INSERT INTO managed_groups(
                    bot_id, group_openid, group_id, group_name, group_finger_memo,
                    group_class_text, group_tags, group_member_num, source,
                    info_synced_at, info_sync_error, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, group_openid) DO UPDATE SET
                    group_id=CASE WHEN excluded.group_id!='' THEN excluded.group_id ELSE managed_groups.group_id END,
                    group_name = CASE
                        WHEN excluded.group_name != '' THEN excluded.group_name
                        ELSE managed_groups.group_name
                    END,
                    group_finger_memo=CASE WHEN excluded.group_finger_memo!='' THEN excluded.group_finger_memo ELSE managed_groups.group_finger_memo END,
                    group_class_text=CASE WHEN excluded.group_class_text!='' THEN excluded.group_class_text ELSE managed_groups.group_class_text END,
                    group_tags=CASE WHEN excluded.group_tags!='[]' THEN excluded.group_tags ELSE managed_groups.group_tags END,
                    group_member_num=COALESCE(excluded.group_member_num, managed_groups.group_member_num),
                    source = excluded.source,
                    info_synced_at=COALESCE(excluded.info_synced_at, managed_groups.info_synced_at),
                    info_sync_error=excluded.info_sync_error,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    bot_id, cleaned, str(group_id or "").strip(), str(group_name or "").strip(),
                    str(group_finger_memo or "").strip(), str(group_class_text or "").strip(),
                    json.dumps(group_tags or [], ensure_ascii=False), group_member_num, source,
                    utc_now() if info_synced else None, str(info_sync_error or "")[:500], utc_now(),
                ),
            )
        return not existed

    def list_groups(self, bot_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM managed_groups WHERE bot_id=? ORDER BY last_seen_at DESC",
                (bot_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["group_tags"] = json.loads(item.get("group_tags") or "[]")
            except ValueError:
                item["group_tags"] = []
            result.append(item)
        return result

    def get_settings(self, bot_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM group_management_settings WHERE bot_id=?", (bot_id,)
            ).fetchone()
        if row is None:
            return {
                "bot_id": bot_id,
                "manual_approval_enabled": True,
                "auto_approval_enabled": True,
                "updated_at": None,
            }
        result = dict(row)
        result["manual_approval_enabled"] = bool(result["manual_approval_enabled"])
        result["auto_approval_enabled"] = bool(result["auto_approval_enabled"])
        return result

    def update_settings(
        self,
        bot_id: str,
        *,
        manual_approval_enabled: bool,
        auto_approval_enabled: bool,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO group_management_settings(
                    bot_id, manual_approval_enabled, auto_approval_enabled, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    manual_approval_enabled=excluded.manual_approval_enabled,
                    auto_approval_enabled=excluded.auto_approval_enabled,
                    updated_at=excluded.updated_at""",
                (bot_id, int(manual_approval_enabled), int(auto_approval_enabled), utc_now()),
            )
        return self.get_settings(bot_id)

    def known_members(self, bot_id: str) -> list[dict[str, str]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT group_openid, member_openid, MAX(username) AS username,
                MAX(updated_at) AS last_seen_at FROM official_join_requests
                WHERE bot_id=? GROUP BY group_openid, member_openid ORDER BY last_seen_at DESC""",
                (bot_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _join_request_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["bot"] = bool(data.pop("is_bot", 0))
        try:
            data["verify_info"] = json.loads(data.get("verify_info") or "{}")
        except ValueError:
            data["verify_info"] = {}
        return data

    def upsert_join_request(
        self,
        bot_id: str,
        payload: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any] | None:
        join_request_id = str(payload.get("join_request_id") or "").strip()
        group_openid = str(payload.get("group_openid") or "").strip()
        member_openid = str(payload.get("member_openid") or "").strip()
        if not join_request_id or not group_openid or not member_openid:
            return None
        auto = payload.get("auto_approved") if isinstance(payload.get("auto_approved"), dict) else {}
        auto_strategy_id = str(auto.get("strategy_id") or "").strip()
        status = "auto_approved" if auto_strategy_id else "pending"
        now = utc_now()
        self.remember_group(bot_id, group_openid, source=source)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO official_join_requests(
                    bot_id, join_request_id, group_openid, member_openid, union_openid,
                    username, risk_tips, apply_at, apply_source, invited_by, is_bot,
                    verify_info, auto_strategy_id, status, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, join_request_id) DO UPDATE SET
                    group_openid=excluded.group_openid,
                    member_openid=excluded.member_openid,
                    union_openid=excluded.union_openid,
                    username=excluded.username,
                    risk_tips=excluded.risk_tips,
                    apply_at=excluded.apply_at,
                    apply_source=excluded.apply_source,
                    invited_by=excluded.invited_by,
                    is_bot=excluded.is_bot,
                    verify_info=excluded.verify_info,
                    auto_strategy_id=CASE
                        WHEN excluded.auto_strategy_id != '' THEN excluded.auto_strategy_id
                        ELSE official_join_requests.auto_strategy_id
                    END,
                    status=CASE
                        WHEN official_join_requests.status IN ('approved','declined')
                            THEN official_join_requests.status
                        ELSE excluded.status
                    END,
                    updated_at=excluded.updated_at
                """,
                (
                    bot_id,
                    join_request_id,
                    group_openid,
                    member_openid,
                    str(payload.get("union_openid") or ""),
                    str(payload.get("username") or ""),
                    str(payload.get("risk_tips") or ""),
                    str(payload.get("apply_at") or ""),
                    str(payload.get("apply_source") or ""),
                    str(payload.get("invited_by") or ""),
                    int(bool(payload.get("bot"))),
                    json.dumps(payload.get("verify_info") or {}, ensure_ascii=False),
                    auto_strategy_id,
                    status,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM official_join_requests WHERE bot_id=? AND join_request_id=?",
                (bot_id, join_request_id),
            ).fetchone()
        return self._join_request_dict(row) if row else None

    def list_join_requests(self, bot_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM official_join_requests
                WHERE bot_id=?
                ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                         apply_at DESC, updated_at DESC
                LIMIT ?
                """,
                (bot_id, max(1, min(int(limit), 2000))),
            ).fetchall()
        return [self._join_request_dict(row) for row in rows]

    def mark_decision(
        self,
        bot_id: str,
        join_request_id: str,
        *,
        decision: str,
        detail: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE official_join_requests
                SET status=?, decision=?, decision_detail=?, decided_at=?, updated_at=?
                WHERE bot_id=? AND join_request_id=?
                """,
                (
                    "approved" if decision == "approve" else "declined",
                    decision,
                    detail,
                    utc_now(),
                    utc_now(),
                    bot_id,
                    join_request_id,
                ),
            )

    def add_log(
        self,
        *,
        bot_id: str,
        action: str,
        success: bool,
        group_openid: str = "",
        member_openid: str = "",
        strategy_id: str = "",
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO group_management_logs(
                    bot_id, action, group_openid, member_openid, strategy_id,
                    success, status_code, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_id,
                    action,
                    group_openid,
                    member_openid,
                    strategy_id,
                    int(bool(success)),
                    status_code,
                    str(detail)[:2000],
                    utc_now(),
                ),
            )

    def list_logs(self, bot_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM group_management_logs WHERE bot_id=? ORDER BY id DESC LIMIT ?",
                (bot_id, max(1, min(int(limit), 500))),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["success"] = bool(data["success"])
            result.append(data)
        return result


group_management_repository = GroupManagementRepository()
