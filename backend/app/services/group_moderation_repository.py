from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "group_moderation.db"
DEFAULT_PENALTY_MINUTES = [10, 60, 1440, 10080]
DEFAULT_CONTENT_KEYWORDS = [
    "发票", "代开", "开票", "贷款", "放款", "借款", "低息", "无抵押", "信用贷",
    "资金周转", "垫资", "套现", "办证", "刻章", "刷单", "招代理", "返利",
]
DEFAULT_NICKNAME_KEYWORDS = ["发票", "代开", "开票", "贷款", "放款", "借款", "办证", "套现"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(value: Any, default: list[Any]) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except ValueError:
            pass
    return list(default)


class GroupModerationRepository:
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
                CREATE TABLE IF NOT EXISTS moderation_settings (
                    bot_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    detect_mobile INTEGER NOT NULL DEFAULT 1,
                    detect_landline INTEGER NOT NULL DEFAULT 1,
                    detect_wechat INTEGER NOT NULL DEFAULT 1,
                    detect_content_keywords INTEGER NOT NULL DEFAULT 1,
                    detect_nickname_keywords INTEGER NOT NULL DEFAULT 1,
                    exempt_admins INTEGER NOT NULL DEFAULT 1,
                    use_official_mute INTEGER NOT NULL DEFAULT 1,
                    penalty_minutes TEXT NOT NULL,
                    permanent_after INTEGER NOT NULL DEFAULT 5,
                    escalation_cooldown_seconds INTEGER NOT NULL DEFAULT 60,
                    warning_cooldown_seconds INTEGER NOT NULL DEFAULT 30,
                    content_keywords TEXT NOT NULL,
                    nickname_keywords TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS moderation_members (
                    id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    member_name TEXT NOT NULL DEFAULT '',
                    trusted INTEGER NOT NULL DEFAULT 0,
                    strike_count INTEGER NOT NULL DEFAULT 0,
                    penalty_level INTEGER NOT NULL DEFAULT 0,
                    blocked_until TEXT,
                    permanent INTEGER NOT NULL DEFAULT 0,
                    last_violation_at TEXT,
                    last_rule TEXT NOT NULL DEFAULT '',
                    last_match TEXT NOT NULL DEFAULT '',
                    last_message_at TEXT,
                    retracted_messages INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    last_warning_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(bot_id, group_openid, member_openid)
                );

                CREATE TABLE IF NOT EXISTS moderation_messages (
                    bot_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY(bot_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS moderation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id TEXT NOT NULL,
                    member_id TEXT,
                    group_openid TEXT NOT NULL DEFAULT '',
                    member_openid TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    rule TEXT NOT NULL DEFAULT '',
                    matched TEXT NOT NULL DEFAULT '',
                    message_excerpt TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL,
                    status_code INTEGER,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_moderation_members_bot ON moderation_members(bot_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_moderation_logs_bot ON moderation_logs(bot_id, created_at DESC);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(moderation_settings)").fetchall()
            }
            if "retract_merged_messages" not in columns:
                connection.execute(
                    "ALTER TABLE moderation_settings ADD COLUMN retract_merged_messages INTEGER NOT NULL DEFAULT 0"
                )
            if "retract_group_cards" not in columns:
                connection.execute(
                    "ALTER TABLE moderation_settings ADD COLUMN retract_group_cards INTEGER NOT NULL DEFAULT 0"
                )
            if "use_official_mute" not in columns:
                connection.execute(
                    "ALTER TABLE moderation_settings ADD COLUMN use_official_mute INTEGER NOT NULL DEFAULT 1"
                )
            special_migrations = {
                "merged_message_action": "TEXT NOT NULL DEFAULT 'retract'",
                "group_card_action": "TEXT NOT NULL DEFAULT 'retract'",
                "special_rule_mute_minutes": "INTEGER NOT NULL DEFAULT 60",
            }
            for column, definition in special_migrations.items():
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE moderation_settings ADD COLUMN {column} {definition}"
                    )

    @staticmethod
    def _settings_dict(row: sqlite3.Row | None, bot_id: str) -> dict[str, Any]:
        if row is None:
            return {
                "bot_id": bot_id,
                "enabled": False,
                "detect_mobile": True,
                "detect_landline": True,
                "detect_wechat": True,
                "detect_content_keywords": True,
                "detect_nickname_keywords": True,
                "exempt_admins": True,
                "use_official_mute": True,
                "retract_merged_messages": False,
                "retract_group_cards": False,
                "merged_message_action": "retract",
                "group_card_action": "retract",
                "special_rule_mute_minutes": 60,
                "penalty_minutes": list(DEFAULT_PENALTY_MINUTES),
                "permanent_after": 5,
                "escalation_cooldown_seconds": 60,
                "warning_cooldown_seconds": 30,
                "content_keywords": list(DEFAULT_CONTENT_KEYWORDS),
                "nickname_keywords": list(DEFAULT_NICKNAME_KEYWORDS),
                "updated_at": None,
            }
        data = dict(row)
        for key in (
            "enabled", "detect_mobile", "detect_landline", "detect_wechat",
            "detect_content_keywords", "detect_nickname_keywords", "exempt_admins",
            "retract_merged_messages", "retract_group_cards", "use_official_mute",
        ):
            data[key] = bool(data.get(key, 0))
        data["penalty_minutes"] = [int(v) for v in _json_list(data.get("penalty_minutes"), DEFAULT_PENALTY_MINUTES)]
        data["content_keywords"] = [str(v) for v in _json_list(data.get("content_keywords"), DEFAULT_CONTENT_KEYWORDS)]
        data["nickname_keywords"] = [str(v) for v in _json_list(data.get("nickname_keywords"), DEFAULT_NICKNAME_KEYWORDS)]
        return data

    def get_settings(self, bot_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM moderation_settings WHERE bot_id = ?", (bot_id,)).fetchone()
            return self._settings_dict(row, bot_id)

    def update_settings(self, bot_id: str, **values: Any) -> dict[str, Any]:
        current = self.get_settings(bot_id)
        current.update(values)
        current["updated_at"] = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO moderation_settings (
                    bot_id, enabled, detect_mobile, detect_landline, detect_wechat,
                    detect_content_keywords, detect_nickname_keywords, exempt_admins,
                    retract_merged_messages, retract_group_cards, use_official_mute,
                    merged_message_action, group_card_action, special_rule_mute_minutes,
                    penalty_minutes, permanent_after,
                    escalation_cooldown_seconds, warning_cooldown_seconds, content_keywords,
                    nickname_keywords, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    detect_mobile = excluded.detect_mobile,
                    detect_landline = excluded.detect_landline,
                    detect_wechat = excluded.detect_wechat,
                    detect_content_keywords = excluded.detect_content_keywords,
                    detect_nickname_keywords = excluded.detect_nickname_keywords,
                    exempt_admins = excluded.exempt_admins,
                    retract_merged_messages = excluded.retract_merged_messages,
                    retract_group_cards = excluded.retract_group_cards,
                    use_official_mute = excluded.use_official_mute,
                    merged_message_action = excluded.merged_message_action,
                    group_card_action = excluded.group_card_action,
                    special_rule_mute_minutes = excluded.special_rule_mute_minutes,
                    penalty_minutes = excluded.penalty_minutes,
                    permanent_after = excluded.permanent_after,
                    escalation_cooldown_seconds = excluded.escalation_cooldown_seconds,
                    warning_cooldown_seconds = excluded.warning_cooldown_seconds,
                    content_keywords = excluded.content_keywords,
                    nickname_keywords = excluded.nickname_keywords,
                    updated_at = excluded.updated_at
                """,
                (
                    bot_id, int(bool(current["enabled"])), int(bool(current["detect_mobile"])),
                    int(bool(current["detect_landline"])), int(bool(current["detect_wechat"])),
                    int(bool(current["detect_content_keywords"])), int(bool(current["detect_nickname_keywords"])),
                    int(bool(current["exempt_admins"])), int(bool(current["retract_merged_messages"])),
                    int(bool(current["retract_group_cards"])), int(bool(current["use_official_mute"])),
                    str(current["merged_message_action"]), str(current["group_card_action"]),
                    int(current["special_rule_mute_minutes"]),
                    json.dumps(current["penalty_minutes"], ensure_ascii=False),
                    int(current["permanent_after"]), int(current["escalation_cooldown_seconds"]),
                    int(current["warning_cooldown_seconds"]), json.dumps(current["content_keywords"], ensure_ascii=False),
                    json.dumps(current["nickname_keywords"], ensure_ascii=False), current["updated_at"],
                ),
            )
        return self.get_settings(bot_id)

    @staticmethod
    def _member_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["trusted"] = bool(data["trusted"])
        data["permanent"] = bool(data["permanent"])
        return data

    def get_member(self, bot_id: str, group_openid: str, member_openid: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM moderation_members WHERE bot_id = ? AND group_openid = ? AND member_openid = ?",
                (bot_id, group_openid, member_openid),
            ).fetchone()
            return self._member_dict(row)

    def get_member_by_id(self, member_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            return self._member_dict(connection.execute("SELECT * FROM moderation_members WHERE id = ?", (member_id,)).fetchone())

    def ensure_member(self, bot_id: str, group_openid: str, member_openid: str, member_name: str = "") -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO moderation_members (id, bot_id, group_openid, member_openid, member_name, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(bot_id, group_openid, member_openid) DO UPDATE SET
                    member_name = CASE WHEN excluded.member_name != '' THEN excluded.member_name ELSE moderation_members.member_name END,
                    updated_at = excluded.updated_at
                """,
                (uuid.uuid4().hex, bot_id, group_openid, member_openid, member_name.strip(), now),
            )
        member = self.get_member(bot_id, group_openid, member_openid)
        if member is None:
            raise RuntimeError("无法创建治理成员状态")
        return member

    def claim_message(self, bot_id: str, message_id: str) -> bool:
        if not message_id:
            return True
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO moderation_messages (bot_id, message_id, processed_at) VALUES (?, ?, ?)",
                (bot_id, message_id, utc_now()),
            )
            return cursor.rowcount == 1

    def apply_penalty(
        self,
        member_id: str,
        *,
        rule: str,
        matched: str,
        strike_count: int,
        penalty_level: int,
        blocked_until: str | None,
        permanent: bool,
        member_name: str,
        now: str,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE moderation_members SET
                    member_name = CASE WHEN ? != '' THEN ? ELSE member_name END,
                    strike_count = ?, penalty_level = ?, blocked_until = ?, permanent = ?,
                    last_violation_at = ?, last_rule = ?, last_match = ?, last_message_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (member_name.strip(), member_name.strip(), strike_count, penalty_level, blocked_until,
                 int(permanent), now, rule, matched[:160], now, now, member_id),
            )
        result = self.get_member_by_id(member_id)
        if result is None:
            raise KeyError("治理成员不存在")
        return result

    def record_retraction(self, member_id: str, *, success: bool, status_code: int | None, detail: str, now: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE moderation_members SET
                    retracted_messages = retracted_messages + ?, last_message_at = ?,
                    last_error = ?, updated_at = ? WHERE id = ?
                """,
                (int(success), now, "" if success else detail[:500], now, member_id),
            )

    def record_warning(self, member_id: str, now: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE moderation_members SET warning_count = warning_count + 1, last_warning_at = ?, updated_at = ? WHERE id = ?",
                (now, now, member_id),
            )

    def set_trusted(self, member_id: str, trusted: bool) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE moderation_members SET trusted = ?, blocked_until = NULL, permanent = 0, updated_at = ? WHERE id = ?",
                (int(trusted), utc_now(), member_id),
            )
        member = self.get_member_by_id(member_id)
        if member is None:
            raise KeyError("治理成员不存在")
        return member

    def release_member(self, member_id: str, *, reset_strikes: bool = False) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            if reset_strikes:
                connection.execute(
                    "UPDATE moderation_members SET strike_count = 0, penalty_level = 0, blocked_until = NULL, permanent = 0, last_error = '', updated_at = ? WHERE id = ?",
                    (utc_now(), member_id),
                )
            else:
                connection.execute(
                    "UPDATE moderation_members SET blocked_until = NULL, permanent = 0, last_error = '', updated_at = ? WHERE id = ?",
                    (utc_now(), member_id),
                )
        member = self.get_member_by_id(member_id)
        if member is None:
            raise KeyError("治理成员不存在")
        return member

    def make_permanent(self, member_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE moderation_members SET permanent = 1, blocked_until = NULL, penalty_level = MAX(penalty_level, 5), updated_at = ? WHERE id = ?",
                (utc_now(), member_id),
            )
        member = self.get_member_by_id(member_id)
        if member is None:
            raise KeyError("治理成员不存在")
        return member

    def list_members(self, bot_id: str, limit: int = 300) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM moderation_members WHERE bot_id = ? ORDER BY permanent DESC, updated_at DESC LIMIT ?",
                (bot_id, limit),
            ).fetchall()
            return [self._member_dict(row) or {} for row in rows]

    def counts(self, bot_id: str, now: str | None = None) -> dict[str, int]:
        current = now or utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                    SUM(CASE WHEN trusted = 1 THEN 1 ELSE 0 END) AS trusted,
                    SUM(CASE WHEN permanent = 1 THEN 1 ELSE 0 END) AS permanent,
                    SUM(CASE WHEN permanent = 1 OR (blocked_until IS NOT NULL AND blocked_until > ?) THEN 1 ELSE 0 END) AS blocked
                FROM moderation_members WHERE bot_id = ?
                """,
                (current, bot_id),
            ).fetchone()
            return {key: int(row[key] or 0) for key in ("total", "trusted", "permanent", "blocked")}

    def add_log(
        self,
        *,
        bot_id: str,
        member_id: str | None,
        group_openid: str = "",
        member_openid: str = "",
        action: str,
        rule: str = "",
        matched: str = "",
        message_excerpt: str = "",
        success: bool,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO moderation_logs (
                    bot_id, member_id, group_openid, member_openid, action, rule, matched,
                    message_excerpt, success, status_code, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (bot_id, member_id, group_openid, member_openid, action, rule, matched[:160],
                 message_excerpt[:240], int(success), status_code, detail[:800], utc_now()),
            )

    def list_logs(self, bot_id: str, limit: int = 120) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM moderation_logs WHERE bot_id = ? ORDER BY id DESC LIMIT ?", (bot_id, limit)
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data["success"] = bool(data["success"])
                result.append(data)
            return result


group_moderation_repository = GroupModerationRepository()
