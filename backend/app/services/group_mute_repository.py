from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATABASE_FILE = DATA_DIR / "group_mute_leases.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class GroupMuteLeaseRepository:
    """Track mute sources so one feature cannot release another feature's mute."""

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
                CREATE TABLE IF NOT EXISTS group_mute_leases (
                    bot_id TEXT NOT NULL,
                    group_openid TEXT NOT NULL,
                    member_openid TEXT NOT NULL,
                    source TEXT NOT NULL,
                    expire_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(bot_id, group_openid, member_openid, source)
                );

                CREATE INDEX IF NOT EXISTS idx_group_mute_member
                    ON group_mute_leases(bot_id, group_openid, member_openid, active);
                """
            )

    def active_leases(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        *,
        exclude_source: str = "",
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        moment = now or datetime.now(timezone.utc)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM group_mute_leases
                WHERE bot_id=? AND group_openid=? AND member_openid=? AND active=1
                """,
                (bot_id, group_openid, member_openid),
            ).fetchall()
        result: list[dict[str, Any]] = []
        expired_sources: list[str] = []
        for row in rows:
            item = dict(row)
            expiry = parse_time(str(item.get("expire_at") or ""))
            if expiry is None or expiry <= moment:
                expired_sources.append(str(item["source"]))
                continue
            if item["source"] == exclude_source:
                continue
            item["expire_at_dt"] = expiry
            result.append(item)
        if expired_sources:
            with self._lock, self._connect() as connection:
                connection.executemany(
                    """
                    UPDATE group_mute_leases SET active=0, updated_at=?
                    WHERE bot_id=? AND group_openid=? AND member_openid=? AND source=?
                    """,
                    [(utc_now(), bot_id, group_openid, member_openid, source) for source in expired_sources],
                )
        return result

    def upsert(
        self,
        bot_id: str,
        group_openid: str,
        member_openid: str,
        source: str,
        expire_at: str,
        *,
        detail: str = "",
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO group_mute_leases(
                    bot_id, group_openid, member_openid, source, expire_at,
                    active, detail, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(bot_id, group_openid, member_openid, source) DO UPDATE SET
                    expire_at=excluded.expire_at,
                    active=1,
                    detail=excluded.detail,
                    updated_at=excluded.updated_at
                """,
                (bot_id, group_openid, member_openid, source, expire_at, detail[:500], now, now),
            )

    def deactivate(self, bot_id: str, group_openid: str, member_openid: str, source: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE group_mute_leases SET active=0, updated_at=?
                WHERE bot_id=? AND group_openid=? AND member_openid=? AND source=?
                """,
                (utc_now(), bot_id, group_openid, member_openid, source),
            )

    def clear_member(self, bot_id: str, group_openid: str, member_openid: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE group_mute_leases SET active=0, updated_at=?
                WHERE bot_id=? AND group_openid=? AND member_openid=?
                """,
                (utc_now(), bot_id, group_openid, member_openid),
            )


group_mute_lease_repository = GroupMuteLeaseRepository()
