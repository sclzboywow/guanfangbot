from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MAX_LOG_ROWS_PER_BOT = 2000
LOG_TABLES = (
    (DATA_DIR / "group_verification.db", "verification_logs"),
    (DATA_DIR / "group_management.db", "group_management_logs"),
    (DATA_DIR / "group_moderation.db", "moderation_logs"),
    (DATA_DIR / "library_delivery.db", "library_delivery_logs"),
)
logger = logging.getLogger(__name__)


def _install_table_retention(database_path: Path, table_name: str) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    trigger_name = f"trim_{table_name}_per_bot"

    with sqlite3.connect(database_path, timeout=30) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if exists is None:
            return

        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {trigger_name}
            AFTER INSERT ON {table_name}
            BEGIN
                DELETE FROM {table_name}
                WHERE bot_id = NEW.bot_id
                  AND id NOT IN (
                      SELECT id FROM {table_name}
                      WHERE bot_id = NEW.bot_id
                      ORDER BY id DESC
                      LIMIT {MAX_LOG_ROWS_PER_BOT}
                  );
            END;
            """
        )
        connection.execute(
            f"""
            DELETE FROM {table_name}
            WHERE id IN (
                SELECT id FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY bot_id
                            ORDER BY id DESC
                        ) AS row_number
                    FROM {table_name}
                ) ranked
                WHERE row_number > {MAX_LOG_ROWS_PER_BOT}
            )
            """
        )


def install_log_retention() -> None:
    """Keep persistent feature logs bounded per bot.

    Event callback logs are already held in a deque(maxlen=100). The SQLite
    feature logs need explicit retention because their tables otherwise grow
    for the lifetime of the deployment.
    """
    for database_path, table_name in LOG_TABLES:
        try:
            _install_table_retention(database_path, table_name)
        except sqlite3.Error:
            logger.exception(
                "Unable to install log retention for %s in %s",
                table_name,
                database_path,
            )
