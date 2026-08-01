from __future__ import annotations

import json
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from app.models.schemas import BotCreate, BotPublic, BotUpdate

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_FILE = DATA_DIR / "bots.json"


class BotRepository:
    """File-backed bot store. Secrets stay server-side and are never returned in full."""

    def __init__(self, path: Path = DATA_FILE) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._bots: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._bots = {}
            self._persist()
            return
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        bots = raw.get("bots", raw if isinstance(raw, dict) else {})
        self._bots = {str(key): value for key, value in bots.items()}

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"bots": self._bots}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _to_public(self, record: dict[str, Any]) -> BotPublic:
        secret = str(record.get("client_secret") or "")
        return BotPublic(
            id=str(record["id"]),
            name=str(record.get("name") or ""),
            description=str(record.get("description") or ""),
            status=record.get("status") or "created",
            role=record.get("role") or "admin",
            app_id=str(record.get("app_id") or ""),
            has_secret=bool(secret),
            avatar_seed=int(record.get("avatar_seed") or 0),
            updated_at=str(record.get("updated_at") or date.today().isoformat()),
            callback_url=str(record.get("callback_url") or ""),
            event_scopes=list(record.get("event_scopes") or []),
        )

    def list(self) -> list[BotPublic]:
        with self._lock:
            return [self._to_public(item) for item in self._bots.values()]

    def get(self, bot_id: str) -> BotPublic | None:
        with self._lock:
            record = self._bots.get(bot_id)
            return self._to_public(record) if record else None

    def get_credentials(self, bot_id: str) -> tuple[str, str] | None:
        with self._lock:
            record = self._bots.get(bot_id)
            if not record:
                return None
            app_id = str(record.get("app_id") or "")
            secret = str(record.get("client_secret") or "")
            if not app_id or not secret:
                return None
            return app_id, secret

    def get_credentials_by_app_id(self, app_id: str) -> tuple[str, str, str] | None:
        """Return (bot_id, app_id, client_secret) for the given AppID."""
        app_id = (app_id or "").strip()
        if not app_id:
            return None
        with self._lock:
            for bot_id, record in self._bots.items():
                if str(record.get("app_id") or "") == app_id:
                    secret = str(record.get("client_secret") or "")
                    if not secret:
                        return None
                    return bot_id, app_id, secret
        return None

    def create(self, payload: BotCreate) -> BotPublic:
        with self._lock:
            bot_id = f"bot-{uuid.uuid4().hex[:10]}"
            record = {
                "id": bot_id,
                "name": payload.name.strip(),
                "description": payload.description.strip(),
                "status": payload.status,
                "role": "admin",
                "app_id": payload.app_id.strip(),
                "client_secret": payload.client_secret.strip(),
                "avatar_seed": abs(hash(payload.app_id)) % 6,
                "updated_at": date.today().isoformat(),
                "callback_url": payload.callback_url.strip(),
                "event_scopes": list(payload.event_scopes),
            }
            self._bots[bot_id] = record
            self._persist()
            return self._to_public(record)

    def update(self, bot_id: str, update: BotUpdate) -> BotPublic | None:
        with self._lock:
            record = self._bots.get(bot_id)
            if record is None:
                return None
            data = update.model_dump(exclude_none=True)
            secret = data.pop("client_secret", None)
            for key, value in data.items():
                if isinstance(value, str):
                    record[key] = value.strip()
                else:
                    record[key] = value
            if secret is not None:
                record["client_secret"] = secret.strip()
            record["updated_at"] = date.today().isoformat()
            self._bots[bot_id] = record
            self._persist()
            return self._to_public(record)

    def delete(self, bot_id: str) -> bool:
        with self._lock:
            if bot_id not in self._bots:
                return False
            del self._bots[bot_id]
            self._persist()
            return True

    def set_status(self, bot_id: str, status: str) -> BotPublic | None:
        with self._lock:
            record = self._bots.get(bot_id)
            if record is None:
                return None
            if record.get("status") != status:
                record["status"] = status
                record["updated_at"] = date.today().isoformat()
                self._bots[bot_id] = record
                self._persist()
            return self._to_public(record)


bot_repository = BotRepository()
