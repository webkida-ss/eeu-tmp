"""In-process account and subscription stores.

For tests and for an application that has not chosen a database yet:
everything is lost on restart, so never select these in production.
"""

from __future__ import annotations

import secrets
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from accounts.models import User
from accounts.settings import DEFAULT_SESSION_TTL_DAYS


def _normalize_email(email: str) -> str:
    return email.strip().lower()


class InMemoryAuthService:
    def __init__(self, session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS) -> None:
        self._session_ttl = timedelta(days=session_ttl_days)
        self._lock = threading.Lock()
        self._users_by_email: dict[str, User] = {}
        self._sessions: dict[str, tuple[str, datetime]] = {}
        self._users_by_id: dict[str, User] = {}

    def login(self, *, email: str, display_name: str | None = None) -> tuple[str, User]:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        with self._lock:
            user = self._users_by_email.get(normalized_email)
            resolved_name = (display_name or "").strip() or normalized_email.split("@")[0]
            if user is None:
                user = User(
                    id=str(uuid.uuid4()),
                    email=normalized_email,
                    display_name=resolved_name,
                )
            elif display_name and display_name.strip():
                user = user.model_copy(update={"display_name": resolved_name})
            self._users_by_email[normalized_email] = user
            self._users_by_id[user.id] = user

            token = secrets.token_urlsafe(32)
            self._sessions[token] = (user.id, datetime.now(UTC) + self._session_ttl)
            return token, user

    def resolve_user(self, access_token: str) -> User | None:
        token = (access_token or "").strip()
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            user_id, expires_at = session
            if expires_at < datetime.now(UTC):
                self._sessions.pop(token, None)
                return None
            return self._users_by_id.get(user_id)

    def logout(self, access_token: str) -> None:
        token = (access_token or "").strip()
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)


class _InMemorySubscriptionState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, Any]] = {}


class InMemorySubscriptionRepository:
    def __init__(self, state: _InMemorySubscriptionState | None = None) -> None:
        self._state = state or _InMemorySubscriptionState()

    @staticmethod
    def shared_state() -> _InMemorySubscriptionState:
        """Create state explicitly shareable by independent repository adapters."""
        return _InMemorySubscriptionState()

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self._state.lock:
            record = self._state.records.get(user_id)
            return deepcopy(record) if record else None

    def upsert(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        with self._state.lock:
            stored = self._next_record(user_id, record, self._state.records.get(user_id))
            self._assert_customer_ownership(user_id, stored.get("stripe_customer_id"))
            self._state.records[user_id] = stored
            return deepcopy(stored)

    def compare_and_swap(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        with self._state.lock:
            current = self._state.records.get(user_id)
            if self._revision(current) != expected_revision:
                return None
            stored = self._next_record(user_id, record, current)
            self._assert_customer_ownership(user_id, stored.get("stripe_customer_id"))
            self._state.records[user_id] = stored
            return deepcopy(stored)

    def find_user_by_customer(self, stripe_customer_id: str) -> str | None:
        if not stripe_customer_id:
            return None
        with self._state.lock:
            owners = {
                user_id
                for user_id, record in self._state.records.items()
                if record.get("stripe_customer_id") == stripe_customer_id
            }
        if len(owners) > 1:
            raise ValueError("Ambiguous Stripe customer ownership requires reconciliation.")
        return next(iter(owners), None)

    @staticmethod
    def _revision(record: dict[str, Any] | None) -> int:
        raw = (record or {}).get("revision", 0)
        return raw if isinstance(raw, int) and raw >= 0 else 0

    def _next_record(
        self,
        user_id: str,
        record: dict[str, Any],
        current: dict[str, Any] | None,
    ) -> dict[str, Any]:
        stored = deepcopy(record)
        current_pending = (current or {}).get("pending_checkout")
        requested_pending = stored.get("pending_checkout")
        if current_pending and not requested_pending:
            stored["pending_checkout"] = deepcopy(current_pending)
        elif current_pending and requested_pending:
            if requested_pending.get("operation_id") != current_pending.get("operation_id"):
                raise ValueError("A pending checkout operation cannot be replaced.")
        stored["user_id"] = user_id
        stored["revision"] = self._revision(current) + 1
        return stored

    def _assert_customer_ownership(self, user_id: str, customer_id: object) -> None:
        if not isinstance(customer_id, str) or not customer_id:
            return
        for owner_id, record in self._state.records.items():
            if owner_id != user_id and record.get("stripe_customer_id") == customer_id:
                raise ValueError("Stripe customer is already owned by another account.")
