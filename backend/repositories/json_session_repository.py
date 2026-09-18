from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from storage.json_list_store import json_list_lock, write_json_list


class JsonSessionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path.resolve()

    def _read_sessions(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            with self._path.open(encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Session document is corrupt") from exc
        if not isinstance(raw, list) or not all(isinstance(session, dict) for session in raw):
            raise ValueError("Session document must be a list of objects")
        return raw

    @property
    def sessions(self) -> list[dict[str, Any]]:
        with json_list_lock(self._path):
            return self._read_sessions()

    def revoke_all(self, user_id: str) -> int:
        with json_list_lock(self._path):
            sessions = self._read_sessions()
            retained = [session for session in sessions if session.get("user_id") != user_id]
            removed = len(sessions) - len(retained)
            if removed:
                write_json_list(self._path, retained)
            return removed
