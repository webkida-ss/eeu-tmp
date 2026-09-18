from __future__ import annotations

from typing import Protocol


class SessionRepository(Protocol):
    def revoke_all(self, user_id: str) -> int:
        """Revoke every session for a user and return the number removed."""
