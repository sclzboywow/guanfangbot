from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote


class LibraryCatalogError(RuntimeError):
    pass


def quote_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not text or "\x00" in text:
        raise LibraryCatalogError("数据表或字段名称无效")
    return '"' + text.replace('"', '""') + '"'


def _readonly_connection(database_path: str) -> sqlite3.Connection:
    path = Path(database_path).expanduser()
    if not path.exists() or not path.is_file():
        raise LibraryCatalogError(f"资料库文件不存在：{path}")
    encoded = quote(str(path.resolve()), safe="/:\\")
    try:
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        raise LibraryCatalogError(f"无法打开资料库：{exc}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = connection.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
    except sqlite3.Error as exc:
        raise LibraryCatalogError(f"无法读取资料表结构：{exc}") from exc
    return {str(row[1]) for row in rows}


def inspect_catalog(settings: dict[str, Any]) -> dict[str, Any]:
    required = {
        str(settings["title_column"]),
        str(settings["category_column"]),
        str(settings["size_column"]),
        str(settings["fsid_column"]),
        str(settings["path_column"]),
    }
    with _readonly_connection(str(settings["database_path"])) as connection:
        columns = _columns(connection, str(settings["table_name"]))
        if not columns:
            raise LibraryCatalogError(f"找不到资料表：{settings['table_name']}")
        missing = sorted(required - columns)
        if missing:
            raise LibraryCatalogError(f"资料表缺少字段：{', '.join(missing)}")
        table = quote_identifier(str(settings["table_name"]))
        try:
            count = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error as exc:
            raise LibraryCatalogError(f"无法读取资料数量：{exc}") from exc
    return {"ready": True, "row_count": count, "columns": sorted(columns)}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_value(term: str) -> str:
    return f"%{_escape_like(term)}%"


def is_hash_pan_path(pan_path: str) -> bool:
    """True when filename looks like a 64-char content hash PDF (current Netdisk naming)."""
    name = str(pan_path or "").rsplit("/", 1)[-1].strip()
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    return len(stem) == 64 and all(ch in "0123456789abcdef" for ch in stem.lower())


def search_catalog(settings: dict[str, Any], keyword: str, limit: int = 5) -> tuple[int, list[dict[str, str]]]:
    query = " ".join(str(keyword or "").split()).strip()
    if not query:
        return 0, []
    terms = [term for term in query.split(" ") if term]
    table = quote_identifier(str(settings["table_name"]))
    title = quote_identifier(str(settings["title_column"]))
    category = quote_identifier(str(settings["category_column"]))
    size = quote_identifier(str(settings["size_column"]))
    fsid = quote_identifier(str(settings["fsid_column"]))
    pan_path = quote_identifier(str(settings["path_column"]))

    with _readonly_connection(str(settings["database_path"])) as connection:
        columns = _columns(connection, str(settings["table_name"]))
        required = {
            str(settings["title_column"]), str(settings["category_column"]),
            str(settings["size_column"]), str(settings["fsid_column"]),
            str(settings["path_column"]),
        }
        missing = sorted(required - columns)
        if missing:
            raise LibraryCatalogError(f"资料表缺少字段：{', '.join(missing)}")
        where = " AND ".join(f"CAST({title} AS TEXT) LIKE ? ESCAPE '\\'" for _ in terms)
        where_params = [_like_value(term) for term in terms]
        try:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}",
                where_params,
            ).fetchone()[0])
            # Pull a wider candidate window so callers can prefer currently shareable paths.
            fetch_limit = max(1, min(80, int(limit)))
            rows = connection.execute(
                f"""
                SELECT
                    CAST({title} AS TEXT) AS title,
                    COALESCE(CAST({category} AS TEXT), '') AS category,
                    COALESCE(CAST({size} AS TEXT), '') AS size,
                    CAST({fsid} AS TEXT) AS fsid,
                    COALESCE(CAST({pan_path} AS TEXT), '') AS pan_path
                FROM {table}
                WHERE {where}
                ORDER BY
                    CASE
                        WHEN CAST({title} AS TEXT) = ? THEN 0
                        WHEN CAST({title} AS TEXT) LIKE ? ESCAPE '\\' THEN 1
                        ELSE 2
                    END,
                    LENGTH(CAST({title} AS TEXT)) ASC,
                    CAST({title} AS TEXT) ASC
                LIMIT ?
                """,
                [*where_params, query, _escape_like(query) + "%", fetch_limit],
            ).fetchall()
        except sqlite3.Error as exc:
            raise LibraryCatalogError(f"检索资料库失败：{exc}") from exc

    results = []
    for row in rows:
        title_text = " ".join(str(row["title"] or "").split()).strip(' "“”')
        fsid_text = str(row["fsid"] or "").strip()
        if not title_text or not fsid_text:
            continue
        results.append({
            "title": title_text,
            "category": " ".join(str(row["category"] or "").split()),
            "size": str(row["size"] or "").strip(),
            "fsid": fsid_text,
            "pan_path": str(row["pan_path"] or "").strip(),
        })
    # Prefer current Netdisk hash filenames while keeping title relevance order.
    preferred = [item for item in results if is_hash_pan_path(item["pan_path"])]
    fallback = [item for item in results if not is_hash_pan_path(item["pan_path"])]
    return total, (preferred + fallback)[: max(1, min(80, int(limit)))]
