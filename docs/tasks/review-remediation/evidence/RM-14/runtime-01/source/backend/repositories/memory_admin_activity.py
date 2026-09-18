from __future__ import annotations

import threading
from datetime import datetime

from repositories.admin_activity import (
    ActivityEvent,
    ActivityOperation,
    ActivityStatus,
    require_aware_datetime,
)


class MemoryAdminActivityRepository:
    def __init__(self) -> None:
        self._events_by_account_source: dict[tuple[str, str], ActivityEvent] = {}
        self._lock = threading.RLock()

    def append(self, event: ActivityEvent) -> ActivityEvent:
        with self._lock:
            key = (event.user_id, event.source_id)
            existing = self._events_by_account_source.get(key)
            if existing is not None:
                return existing
            self._events_by_account_source[key] = event
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
        with self._lock:
            events = [
                event
                for event in self._events_by_account_source.values()
                if event.user_id == user_id
                and start <= event.recorded_at < end
                and (operation is None or event.operation == operation)
                and (status is None or event.status == status)
            ]
        return sorted(events, key=lambda event: (event.recorded_at, event.id))
