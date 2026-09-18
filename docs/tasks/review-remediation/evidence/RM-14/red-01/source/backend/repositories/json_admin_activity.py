from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage.json_list_store import json_list_lock, read_json_list, write_json_list

from repositories.admin_activity import (
    ActivityEvent,
    ActivityOperation,
    ActivityStatus,
    require_aware_datetime,
)


def _required_string(record: dict[str, Any], name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Persisted activity {name} must be a non-empty string")
    return value


def _nullable_string(record: dict[str, Any], name: str) -> str | None:
    value = record.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Persisted activity {name} must be a string or null")
    return value


def _event_from_record(record: dict[str, Any]) -> ActivityEvent:
    recorded_at_value = _required_string(record, "recorded_at")
    try:
        recorded_at = datetime.fromisoformat(recorded_at_value)
    except ValueError as exc:
        raise ValueError("Persisted activity recorded_at must be ISO 8601") from exc
    require_aware_datetime("Persisted activity recorded_at", recorded_at)

    return ActivityEvent(
        id=_required_string(record, "id"),
        source_id=_required_string(record, "source_id"),
        user_id=_required_string(record, "user_id"),
        operation=_required_string(record, "operation"),  # type: ignore[arg-type]
        status=_required_string(record, "status"),  # type: ignore[arg-type]
        recorded_at=recorded_at.astimezone(UTC),
        error_code=_nullable_string(record, "error_code"),
        input_tokens=record.get("input_tokens"),
        output_tokens=record.get("output_tokens"),
        tokens=record.get("tokens"),
        actual_cost_micro_usd=record.get("actual_cost_micro_usd"),
        model=_nullable_string(record, "model"),
    )


def _event_to_record(event: ActivityEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "source_id": event.source_id,
        "user_id": event.user_id,
        "operation": event.operation,
        "status": event.status,
        "recorded_at": event.recorded_at.astimezone(UTC).isoformat(),
        "error_code": event.error_code,
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "tokens": event.tokens,
        "actual_cost_micro_usd": event.actual_cost_micro_usd,
        "model": event.model,
    }


class JsonAdminActivityRepository:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self._path = path
        lock_key = str(path.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(lock_key, threading.RLock())

    def append(self, event: ActivityEvent) -> ActivityEvent:
        with self._lock, json_list_lock(self._path):
            records = read_json_list(self._path)
            for record in records:
                existing = _event_from_record(record)
                if existing.source_id == event.source_id:
                    return existing
            records.append(_event_to_record(event))
            write_json_list(self._path, records)
            return event

    def query(
        self,
        *,
        user_id: str,
        start: datetime,
        end: datetime,
        operation: ActivityOperation | None = None,
        status: ActivityStatus | None = None,
    ) -> list[ActivityEvent]:
        require_aware_datetime("start", start)
        require_aware_datetime("end", end)
        with self._lock, json_list_lock(self._path):
            events = [_event_from_record(record) for record in read_json_list(self._path)]
        matching = [
            event
            for event in events
            if event.user_id == user_id
            and start <= event.recorded_at < end
            and (operation is None or event.operation == operation)
            and (status is None or event.status == status)
        ]
        return sorted(matching, key=lambda event: (event.recorded_at, event.id))
