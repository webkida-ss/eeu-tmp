from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime

import schemas
from repositories.admin_account_control import (
    AccountStatus,
    AdminAccountControlRepository,
    TransitionResult,
    normalize_reason,
    normalize_utc,
)
from repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class TargetUserNotFoundError(Exception):
    pass


class SessionRevocationError(Exception):
    def __init__(self, correlation_id: str) -> None:
        super().__init__(
            f"Account was suspended, but session revocation failed "
            f"(correlation_id={correlation_id})"
        )
        self.correlation_id = correlation_id


class AdminAccounts:
    def __init__(
        self,
        controls: AdminAccountControlRepository,
        sessions: SessionRepository,
        *,
        user_exists: Callable[[str], bool],
    ) -> None:
        self._controls = controls
        self._sessions = sessions
        self._user_exists = user_exists

    def suspend(
        self,
        *,
        target_user_id: str,
        actor_user_id: str,
        actor_email: str,
        reason: str,
        correlation_id: str,
        occurred_at: datetime | None = None,
    ) -> TransitionResult:
        result = self._transition(
            target_user_id=target_user_id,
            desired_status="suspended",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            reason=reason,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        # Retry revocation even for an idempotent transition: a previous call
        # may have committed the suspension before session storage failed.
        try:
            self._sessions.revoke_all(target_user_id)
        except Exception:
            logger.error(
                "Session revocation failed after suspension correlation_id=%s",
                correlation_id,
            )
            raise SessionRevocationError(correlation_id) from None
        return result

    def reactivate(
        self,
        *,
        target_user_id: str,
        actor_user_id: str,
        actor_email: str,
        reason: str,
        correlation_id: str,
        occurred_at: datetime | None = None,
    ) -> TransitionResult:
        return self._transition(
            target_user_id=target_user_id,
            desired_status="active",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            reason=reason,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )

    def _transition(
        self,
        *,
        target_user_id: str,
        desired_status: AccountStatus,
        actor_user_id: str,
        actor_email: str,
        reason: str,
        correlation_id: str,
        occurred_at: datetime | None,
    ) -> TransitionResult:
        target = self._required("target_user_id", target_user_id)
        actor = self._required("actor_user_id", actor_user_id)
        email = self._required("actor_email", actor_email).lower()
        normalized_reason = normalize_reason(reason)
        correlation = self._required("correlation_id", correlation_id)
        if not _SAFE_CORRELATION_ID.fullmatch(correlation):
            raise ValueError(
                "correlation_id may contain only letters, digits, '.', '_', ':', or '-'"
            )
        timestamp = normalize_utc("occurred_at", occurred_at or datetime.now(UTC))
        if not self._user_exists(target):
            raise TargetUserNotFoundError(target)
        return self._controls.transition(
            target_user_id=target,
            desired_status=desired_status,
            actor_user_id=actor,
            actor_email=email,
            reason=normalized_reason,
            correlation_id=correlation,
            occurred_at=timestamp,
            audit_id=schemas.generate_uuid7(),
        )

    @staticmethod
    def _required(name: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} must not be empty")
        return normalized
