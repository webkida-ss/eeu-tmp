from __future__ import annotations

from typing import Any

from storage.dynamodb_keys import PHRASE_SK_PREFIX, phrase_sk, user_pk
from storage.dynamodb_store import DynamoDbStore


class DynamoPhraseRepository:
    def __init__(self, store: DynamoDbStore) -> None:
        self._store = store

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        phrases = self._store.query_by_pk(user_pk(user_id), sk_prefix=PHRASE_SK_PREFIX)
        return [item for item in phrases if item.get("user_id") == user_id]

    def create(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        stored = dict(record)
        stored["user_id"] = user_id
        phrase_id = stored.get("id")
        if not isinstance(phrase_id, str) or not phrase_id:
            raise ValueError("Phrase id is required.")
        self._store.put_document(user_pk(user_id), phrase_sk(phrase_id), stored)
        return stored
