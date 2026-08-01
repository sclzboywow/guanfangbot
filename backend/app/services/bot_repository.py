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

    @staticmethod
    def _display_name(app_id: str) -> str:
        suffix = app_id[-6:] if len(app_id) > 6 else app_id
        return f"机器人 {suffix}"

    def _to_public(self, record: dict[str, Any]) -> BotPublic:
        secret = str(record.get("client_secret") or "")
        app_id = str(record.get("app_id") or "")
        return BotPublic(
            id=str(record["id"]),
            name=str(record.get("name") or self._display_name(app_id)),
            description=str(record.get("description") or ""),
            status=record.get("status") or "created",
            role=record.get("role") or "admin",
            app_id=app_id,
            has_secret=bool(secret),
            avatar_seed=int(record.get("avatar_seed") or 0),
            avatar_url=str(record.get("avatar_url") or ""),
            updated_at=str(record.get("updated_at") or date.today().isoformat()),
            callback_url=str(record.get("callback_url") or ""),
            event_scopes=list(record.get("event_scopes") or []),
        )

    def _find_by_app_id(self, app_id: str, *, exclude_bot_id: str | None = None) -> str | None:
        for bot_id, record in self._bots.items():
            if bot_id == exclude_bot_id:
                continue
            if str(record.get("app_id") or "") == app_id:
                return bot_id
        return None

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
            bot_id = self._find_by_app_id(app_id)
            if bot_id is None:
                return None
            record = self._bots[bot_id]
            secret = str(record.get("client_secret") or "")
            if not secret:
                return None
            return bot_id, app_id, secret

    def get_event_detection(self, bot_id: str) -> tuple[str | None, dict[str, str]] | None:
        with self._lock:
            record = self._bots.get(bot_id)
            if record is None:
                return None
            verified_at = str(record.get("callback_verified_at") or "") or None
            observed = {
                str(code): str(received_at)
                for code, received_at in dict(record.get("observed_events") or {}).items()
            }
            return verified_at, observed

    def create(self, payload: BotCreate) -> BotPublic:
        with self._lock:
            if self._find_by_app_id(payload.app_id) is not None:
                raise ValueError("该 AppID 已经存在")
            bot_id = f"bot-{uuid.uuid4().hex[:10]}"
            record = {
                "id": bot_id,
                "name": self._display_name(payload.app_id),
                "description": "",
                "status": "created",
                "role": "admin",
                "app_id": payload.app_id,
                "client_secret": payload.client_secret,
                "avatar_seed": abs(hash(payload.app_id)) % 6,
                "avatar_url": "",
                "updated_at": date.today().isoformat(),
                "callback_url": payload.callback_url,
                "event_scopes": [],
                "callback_verified_at": "",
                "observed_events": {},
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
            new_app_id = data.get("app_id")
            if new_app_id and self._find_by_app_id(new_app_id, exclude_bot_id=bot_id) is not None:
                raise ValueError("该 AppID 已经存在")

            app_changed = bool(new_app_id and new_app_id != str(record.get("app_id") or ""))
            callback_changed = "callback_url" in data and data["callback_url"] != str(record.get("callback_url") or "")
            secret = data.pop("client_secret", None)
            secret_changed = secret is not None

            for key, value in data.items():
                record[key] = value.strip() if isinstance(value, str) else value
            if app_changed:
                record["name"] = self._display_name(str(new_app_id))
                record["avatar_seed"] = abs(hash(str(new_app_id))) % 6
                record["status"] = "created"
                record["observed_events"] = {}
            if secret is not None:
                record["client_secret"] = secret.strip()
                record["status"] = "created"
            if app_changed or callback_changed or secret_changed:
                record["callback_verified_at"] = ""
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

    def mark_callback_verified(self, bot_id: str, verified_at: str) -> None:
        with self._lock:
            record = self._bots.get(bot_id)
            if record is None:
                return
            record["callback_verified_at"] = verified_at
            record["status"] = "online"
            self._bots[bot_id] = record
            self._persist()

    def mark_event_observed(self, bot_id: str, event_type: str, received_at: str) -> None:
        with self._lock:
            record = self._bots.get(bot_id)
            if record is None:
                return
            observed = dict(record.get("observed_events") or {})
            observed[event_type] = received_at
            record["observed_events"] = observed
            record["status"] = "online"
            self._bots[bot_id] = record
            self._persist()

    def set_profile(self, bot_id: str, *, name: str | None = None, avatar_url: str | None = None) -> BotPublic | None:
        with self._lock:
            record = self._bots.get(bot_id)
            if record is None:
                return None
            changed = False
            if name is not None:
                cleaned = name.strip()
                if cleaned and record.get("name") != cleaned:
                    record["name"] = cleaned
                    changed = True
            if avatar_url is not None:
                cleaned_avatar = avatar_url.strip()
                if record.get("avatar_url") != cleaned_avatar:
                    record["avatar_url"] = cleaned_avatar
                    changed = True
            if changed:
                record["updated_at"] = date.today().isoformat()
                self._bots[bot_id] = record
                self._persist()
            return self._to_public(record)


bot_repository = BotRepository()
