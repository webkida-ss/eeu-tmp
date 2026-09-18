from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

AccountStatus = Literal["active", "suspended"]


def normalize_utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def normalize_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise ValueError("reason must be a string")
    normalized = reason.strip()
    if not normalized:
        raise ValueError("reason must not be empty")
    if len(normalized) > 500:
        raise ValueError("reason must be at most 500 characters")
    return normalized


def normalize_required(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def require_uuid7(name: str, value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a UUID v7") from exc
    if parsed.version != 7 or parsed.variant != uuid.RFC_4122:
        raise ValueError(f"{name} must be a UUID v7")
    return str(parsed)


@dataclass(frozen=True)
class AccountControl:
    user_id: str
    status: AccountStatus
    suspended_at: datetime | None = None
    suspension_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id must not be empty")
        if self.status not in ("active", "suspended"):
            raise ValueError("status must be active or suspended")
        if self.status == "active":
            if self.suspended_at is not None or self.suspension_reason is not None:
                raise ValueError("active controls cannot have suspension fields")
            return
        if self.suspended_at is None or self.suspension_reason is None:
            raise ValueError("suspended controls require suspension fields")
        object.__setattr__(self, "suspended_at", normalize_utc("suspended_at", self.suspended_at))
        object.__setattr__(self, "suspension_reason", normalize_reason(self.suspension_reason))


@dataclass(frozen=True)
class AdminAuditEvent:
    id: str
    target_user_id: str
    previous_status: AccountStatus
    new_status: AccountStatus
    actor_user_id: str
    actor_email: str
    reason: str
    correlation_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_uuid7("id", self.id))
        for name in (
            "target_user_id",
            "actor_user_id",
            "actor_email",
            "correlation_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must not be empty")
        if self.previous_status not in ("active", "suspended"):
            raise ValueError("previous_status must be active or suspended")
        if self.new_status not in ("active", "suspended"):
            raise ValueError("new_status must be active or suspended")
        object.__setattr__(self, "reason", normalize_reason(self.reason))
        object.__setattr__(self, "occurred_at", normalize_utc("occurred_at", self.occurred_at))


@dataclass(frozen=True)
class TransitionResult:
    control: AccountControl
    changed: bool
    audit_event: AdminAuditEvent | None


@dataclass(frozen=True)
class AuditPage:
    events: tuple[AdminAuditEvent, ...]
    next_cursor: str | None


class AdminAccountControlRepository(Protocol):
    def get_control(self, user_id: str) -> AccountControl: ...

    def transition(
        self,
        *,
        target_user_id: str,
        desired_status: AccountStatus,
        actor_user_id: str,
        actor_email: str,
        reason: str,
        correlation_id: str,
        occurred_at: datetime,
        audit_id: str,
    ) -> TransitionResult: ...

    def query_audits(
        self,
        *,
        target_user_id: str | None = None,
        actor_user_id: str | None = None,
        new_status: AccountStatus | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AuditPage: ...
