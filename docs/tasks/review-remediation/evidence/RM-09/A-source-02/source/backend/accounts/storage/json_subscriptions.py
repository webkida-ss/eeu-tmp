"""JSON-file subscription store (local development default)."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from accounts.storage.json_store import json_list_lock, read_json_list, write_json_list


class JsonSubscriptionRepository:
    """Cross-process safe subscription records with revision-based writes."""

    _locks_guard = threading.Lock()
    _locks: dict[Path, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        with self._locks_guard:
            self._lock = self._locks.setdefault(self._path, threading.RLock())

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, json_list_lock(self._path):
            record = self._find(read_json_list(self._path), user_id)
            return copy.deepcopy(record) if record is not None else None

    def upsert(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        """Write a legacy update without erasing a pending checkout owner."""
        with self._lock, json_list_lock(self._path):
            items = read_json_list(self._path)
            current = self._find(items, user_id)
            stored = self._next_record(user_id, record, current, allow_pending_transition=False)
            self._assert_customer_ownership(items, user_id, stored.get("stripe_customer_id"))
            self._replace(items, user_id, stored)
            write_json_list(self._path, items)
            return copy.deepcopy(stored)

    def compare_and_swap(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        """Atomically advance one record only from its expected revision."""
        with self._lock, json_list_lock(self._path):
            items = read_json_list(self._path)
            current = self._find(items, user_id)
            if self._revision(current) != expected_revision:
                return None
            stored = self._next_record(user_id, record, current, allow_pending_transition=True)
            self._assert_customer_ownership(items, user_id, stored.get("stripe_customer_id"))
            self._replace(items, user_id, stored)
            write_json_list(self._path, items)
            return copy.deepcopy(stored)

    def find_user_by_customer(self, stripe_customer_id: str) -> str | None:
        if not stripe_customer_id:
            return None
        with self._lock, json_list_lock(self._path):
            owners = {
                item.get("user_id")
                for item in read_json_list(self._path)
                if item.get("stripe_customer_id") == stripe_customer_id and item.get("user_id")
            }
        if len(owners) > 1:
            raise ValueError("Ambiguous Stripe customer ownership requires reconciliation.")
        return next(iter(owners), None)

    @staticmethod
    def _find(items: list[dict[str, Any]], user_id: str) -> dict[str, Any] | None:
        return next((item for item in items if item.get("user_id") == user_id), None)

    @staticmethod
    def _revision(record: dict[str, Any] | None) -> int:
        raw = (record or {}).get("revision", 0)
        return raw if isinstance(raw, int) and raw >= 0 else 0

    def _next_record(
        self,
        user_id: str,
        record: dict[str, Any],
        current: dict[str, Any] | None,
        *,
        allow_pending_transition: bool,
    ) -> dict[str, Any]:
        stored = copy.deepcopy(record)
        current_pending = (current or {}).get("pending_checkout")
        requested_pending = stored.get("pending_checkout")
        if current_pending and not allow_pending_transition:
            stored["pending_checkout"] = copy.deepcopy(current_pending)
        elif current_pending:
            self._validate_pending_transition(current_pending, requested_pending)
        stored["user_id"] = user_id
        stored["revision"] = self._revision(current) + 1
        return stored

    @staticmethod
    def _validate_pending_transition(
        current: dict[str, Any], requested: object) -> None:
        if not isinstance(requested, dict):
            raise ValueError("A pending checkout operation cannot be removed by a stale writer.")
        immutable = (
            "operation_id",
            "user_id",
            "requested_plan",
            "price_id",
            "success_url",
            "cancel_url",
            "stripe_customer_id",
            "customer_choice",
            "email",
            "idempotency_key",
            "operation_metadata",
        )
        if current.get("state") == "terminal" and current.get("terminal_proof"):
            replacement_operation_id = requested.get("operation_id")
            if (
                requested.get("state") != "reserved"
                or not isinstance(replacement_operation_id, str)
                or replacement_operation_id == current.get("operation_id")
            ):
                raise ValueError(
                    "A terminal checkout can only be replaced by a new reserved operation."
                )
            return
        if any(requested.get(field) != current.get(field) for field in immutable):
            raise ValueError("A pending checkout operation cannot be replaced.")
        for field in ("creation_attempted_at", "stripe_checkout_session_id", "url", "expires_at"):
            if current.get(field) is not None and requested.get(field) != current.get(field):
                raise ValueError("Pending checkout evidence cannot be replaced.")
        states = {
            "reserved": 0,
            "attempted": 1,
            "created": 2,
            "adopted": 2,
            "activated": 2,
            "terminal": 3,
        }
        if states.get(str(requested.get("state")), -1) < states.get(str(current.get("state")), -1):
            raise ValueError("Pending checkout state cannot move backwards.")

    @staticmethod
    def _assert_customer_ownership(
        items: list[dict[str, Any]], user_id: str, customer_id: object
    ) -> None:
        if not isinstance(customer_id, str) or not customer_id:
            return
        for item in items:
            if item.get("user_id") != user_id and item.get("stripe_customer_id") == customer_id:
                raise ValueError("Stripe customer is already owned by another account.")

    @staticmethod
    def _replace(items: list[dict[str, Any]], user_id: str, record: dict[str, Any]) -> None:
        items[:] = [item for item in items if item.get("user_id") != user_id]
        items.append(record)
