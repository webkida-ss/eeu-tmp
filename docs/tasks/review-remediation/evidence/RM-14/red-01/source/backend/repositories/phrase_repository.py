from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from storage.json_list_store import read_json_list, write_json_list


class PhraseRepository(Protocol):
    def list_for_user(self, user_id: str) -> list[dict[str, Any]]: ...

    def create(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]: ...


class JsonPhraseRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return [item for item in read_json_list(self._path) if item.get("user_id") == user_id]

    def create(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        stored = dict(record)
        stored["user_id"] = user_id
        phrases = read_json_list(self._path)
        phrases.insert(0, stored)
        write_json_list(self._path, phrases)
        return stored
