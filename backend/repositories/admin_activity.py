from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

ActivityOperation = Literal["article", "chat"]
ActivityStatus = Literal["success", "failed", "quota_blocked"]


def require_aware_datetime(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class ActivityEvent:
    id: str
    source_id: str
    user_id: str
    operation: ActivityOperation
    status: ActivityStatus
    recorded_at: datetime
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens: int | None = None
    actual_cost_micro_usd: int | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in ("article", "chat"):
            raise ValueError(f"Unsupported activity operation: {self.operation}")
        if self.status not in ("success", "failed", "quota_blocked"):
            raise ValueError(f"Unsupported activity status: {self.status}")
        require_aware_datetime("recorded_at", self.recorded_at)
        for name in (
            "input_tokens",
            "output_tokens",
            "tokens",
            "actual_cost_micro_usd",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")


class AdminActivityRepository(Protocol):
    def append(self, event: ActivityEvent) -> ActivityEvent:
        """Persist an event, returning the original for a duplicate account/source pair."""

    def query(
        self,
        *,
        user_id: str,
        start: datetime,
        end: datetime,
        operation: ActivityOperation | None = None,
        status: ActivityStatus | None = None,
    ) -> list[ActivityEvent]:
        """Return events in the inclusive-start, exclusive-end time range."""
