from __future__ import annotations

import threading
from datetime import datetime

from repositories.admin_account_control import (
    AccountControl,
    AccountStatus,
    AdminAuditEvent,
    AuditPage,
    TransitionResult,
    normalize_reason,
    normalize_required,
    normalize_utc,
    require_uuid7,
)


class MemoryAdminAccountControlRepository:
    def __init__(self) -> None:
        self._controls: dict[str, AccountControl] = {}
        self._audits: list[AdminAuditEvent] = []
        self._lock = threading.RLock()

    def get_control(self, user_id: str) -> AccountControl:
        with self._lock:
            return self._controls.get(user_id, AccountControl(user_id=user_id, status="active"))

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
    ) -> TransitionResult:
        normalized_reason = normalize_reason(reason)
        timestamp = normalize_utc("occurred_at", occurred_at)
        normalized_audit_id = require_uuid7("audit_id", audit_id)
        target_user_id = normalize_required("target_user_id", target_user_id)
        actor_user_id = normalize_required("actor_user_id", actor_user_id)
        actor_email = normalize_required("actor_email", actor_email)
        correlation_id = normalize_required("correlation_id", correlation_id)
        if desired_status not in ("active", "suspended"):
            raise ValueError("desired_status must be active or suspended")

        with self._lock:
            current = self._controls.get(
                target_user_id,
                AccountControl(user_id=target_user_id, status="active"),
            )
            if current.status == desired_status:
                return TransitionResult(current, False, None)

            control = (
                AccountControl(
                    user_id=target_user_id,
                    status="suspended",
                    suspended_at=timestamp,
                    suspension_reason=normalized_reason,
                )
                if desired_status == "suspended"
                else AccountControl(user_id=target_user_id, status="active")
            )
            event = AdminAuditEvent(
                id=normalized_audit_id,
                target_user_id=target_user_id,
                previous_status=current.status,
                new_status=desired_status,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                reason=normalized_reason,
                correlation_id=correlation_id,
                occurred_at=timestamp,
            )
            self._controls[target_user_id] = control
            self._audits.append(event)
            return TransitionResult(control, True, event)

    def query_audits(
        self,
        *,
        target_user_id: str | None = None,
        actor_user_id: str | None = None,
        new_status: AccountStatus | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AuditPage:
        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        try:
            offset = int(cursor) if cursor is not None else 0
        except ValueError as exc:
            raise ValueError("cursor must be a non-negative integer") from exc
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer")

        with self._lock:
            matching = sorted(
                (
                    event
                    for event in self._audits
                    if (target_user_id is None or event.target_user_id == target_user_id)
                    and (actor_user_id is None or event.actor_user_id == actor_user_id)
                    and (new_status is None or event.new_status == new_status)
                ),
                key=lambda event: (event.occurred_at, event.id),
            )
        page = tuple(matching[offset : offset + limit])
        next_offset = offset + len(page)
        return AuditPage(
            events=page,
            next_cursor=str(next_offset) if next_offset < len(matching) else None,
        )
