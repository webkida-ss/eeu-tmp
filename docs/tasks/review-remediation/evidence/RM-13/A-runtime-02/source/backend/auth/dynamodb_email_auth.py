"""DynamoDB-backed `accounts.ports.AuthService`.

Lives here rather than inside `accounts` because it writes into Untangle's
single-table design (see storage/dynamodb_keys.py). The package defines
the port; the application supplies the adapter and injects it at the
composition root.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from accounts.models import User
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from core.ids import generate_uuid7
from storage.dynamodb_keys import SK_PROFILE, SK_SESSION, SK_USER, email_pk, session_pk, user_pk
from storage.dynamodb_store import DOCUMENT_ATTRIBUTE, DynamoDbStore

_SERIALIZER = TypeSerializer()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class DynamoEmailAuthService:
    def __init__(
        self,
        store: DynamoDbStore,
        session_ttl_days: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._session_ttl = timedelta(days=session_ttl_days)
        self._clock = clock or (lambda: datetime.now(UTC))

    def login(self, *, email: str, display_name: str | None = None) -> tuple[str, User]:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        user_record = self._get_user_by_email(normalized_email)
        if user_record is None:
            user_record = {
                "id": generate_uuid7(),
                "email": normalized_email,
                "display_name": (display_name or normalized_email.split("@")[0]).strip()
                or normalized_email,
                "created_at": self._clock().isoformat(),
            }
            try:
                self._store.transact_write(
                    [
                        _conditional_put(
                            self._store.table_name,
                            email_pk(normalized_email),
                            SK_USER,
                            {"user_id": user_record["id"]},
                        ),
                        _conditional_put(
                            self._store.table_name,
                            user_pk(user_record["id"]),
                            SK_PROFILE,
                            user_record,
                        ),
                    ]
                )
            except ClientError as exc:
                if not _is_conditional_identity_conflict(exc):
                    raise
                user_record = self._get_user_by_email(normalized_email, consistent_read=True)
                if user_record is None:
                    raise ValueError("Account identity could not be resolved.") from None
        elif display_name and display_name.strip():
            user_record["display_name"] = display_name.strip()
            self._store.put_document(user_pk(user_record["id"]), SK_PROFILE, user_record)

        user = User(
            id=user_record["id"],
            email=user_record["email"],
            display_name=user_record.get("display_name") or normalized_email,
        )
        access_token = self._create_session(user.id)
        return access_token, user

    def resolve_user(self, access_token: str) -> User | None:
        token = access_token.strip()
        if not token:
            return None

        session = self._store.get_document(session_pk(token), SK_SESSION)
        if not session:
            return None

        expires_at_raw = session.get("expires_at")
        if isinstance(expires_at_raw, str):
            try:
                expires_at = datetime.fromisoformat(expires_at_raw)
            except ValueError:
                self._store.delete(session_pk(token), SK_SESSION)
                return None
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= self._clock():
                self._store.delete(session_pk(token), SK_SESSION)
                return None

        user_id = session.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return None

        user_record = self._store.get_document(user_pk(user_id), SK_PROFILE)
        if not user_record:
            return None

        return User(
            id=user_record["id"],
            email=user_record["email"],
            display_name=user_record.get("display_name") or user_record["email"],
        )

    def logout(self, access_token: str) -> None:
        token = access_token.strip()
        if not token:
            return
        self._store.delete(session_pk(token), SK_SESSION)

    def _get_user_by_email(
        self, normalized_email: str, *, consistent_read: bool = False
    ) -> dict[str, Any] | None:
        email_lookup = self._store.get_document(
            email_pk(normalized_email), SK_USER, consistent_read=consistent_read
        )
        if not email_lookup:
            return None

        user_id = email_lookup.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return None

        user_record = self._store.get_document(
            user_pk(user_id), SK_PROFILE, consistent_read=consistent_read
        )
        if not user_record:
            return None
        if user_record.get("id") != user_id:
            return None
        if user_record.get("email") != normalized_email:
            return None
        return user_record

    def _create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._store.put_document(
            session_pk(token),
            SK_SESSION,
            {
                "token": token,
                "user_id": user_id,
                "created_at": now.isoformat(),
                "expires_at": (now + self._session_ttl).isoformat(),
            },
        )
        return token


def _conditional_put(
    table_name: str,
    partition_key: str,
    sort_key: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    item = {
        "pk": partition_key,
        "sk": sort_key,
        DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
    }
    return {
        "Put": {
            "TableName": table_name,
            "Item": {field: _SERIALIZER.serialize(value) for field, value in item.items()},
            "ConditionExpression": "attribute_not_exists(pk) AND attribute_not_exists(sk)",
        }
    }


def _is_conditional_identity_conflict(exc: ClientError) -> bool:
    if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    reasons = exc.response.get("CancellationReasons")
    if not isinstance(reasons, list) or not reasons:
        return False
    if not all(
        isinstance(reason, dict) and reason.get("Code") in {"None", "ConditionalCheckFailed"}
        for reason in reasons
    ):
        return False
    return any(reason["Code"] == "ConditionalCheckFailed" for reason in reasons)
