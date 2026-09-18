from __future__ import annotations

import threading
from typing import Any


class MemorySessionRepository:
    def __init__(self, sessions: list[dict[str, Any]] | None = None) -> None:
        self.sessions = list(sessions or [])
        self._lock = threading.RLock()

    def revoke_all(self, user_id: str) -> int:
        with self._lock:
            retained = [session for session in self.sessions if session.get("user_id") != user_id]
            removed = len(self.sessions) - len(retained)
            self.sessions[:] = retained
            return removed
