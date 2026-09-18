from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage.json_list_store import json_list_lock

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


def _required_string(record: dict[str, Any], name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Persisted {name} must be a non-empty string")
    return value


def _parse_datetime(record: dict[str, Any], name: str) -> datetime:
    raw = _required_string(record, name)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Persisted {name} must be ISO 8601") from exc
    return normalize_utc(f"Persisted {name}", value)


def _control_from_record(user_id: str, record: dict[str, Any]) -> AccountControl:
    status = _required_string(record, "status")
    if status == "active":
        return AccountControl(user_id=user_id, status="active")
    if status != "suspended":
        raise ValueError("Persisted control status is invalid")
    return AccountControl(
        user_id=user_id,
        status="suspended",
        suspended_at=_parse_datetime(record, "suspended_at"),
        suspension_reason=_required_string(record, "suspension_reason"),
    )


def _control_to_record(control: AccountControl) -> dict[str, Any]:
    return {
        "status": control.status,
        "suspended_at": (
            control.suspended_at.astimezone(UTC).isoformat() if control.suspended_at else None
        ),
        "suspension_reason": control.suspension_reason,
    }


def _audit_from_record(record: dict[str, Any]) -> AdminAuditEvent:
    return AdminAuditEvent(
        id=_required_string(record, "id"),
        target_user_id=_required_string(record, "target_user_id"),
        previous_status=_required_string(record, "previous_status"),  # type: ignore[arg-type]
        new_status=_required_string(record, "new_status"),  # type: ignore[arg-type]
        actor_user_id=_required_string(record, "actor_user_id"),
        actor_email=_required_string(record, "actor_email"),
        reason=_required_string(record, "reason"),
        correlation_id=_required_string(record, "correlation_id"),
        occurred_at=_parse_datetime(record, "occurred_at"),
    )


def _audit_to_record(event: AdminAuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "target_user_id": event.target_user_id,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "actor_user_id": event.actor_user_id,
        "actor_email": event.actor_email,
        "reason": event.reason,
        "correlation_id": event.correlation_id,
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
    }


class JsonAdminAccountControlRepository:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self._path = path
        with self._locks_guard:
            self._lock = self._locks.setdefault(str(path.resolve()), threading.RLock())

    def _read_document(
        self,
    ) -> tuple[dict[str, AccountControl], list[AdminAuditEvent]]:
        if not self._path.exists():
            return {}, []
        try:
            with self._path.open(encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Admin control document is corrupt") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError("Admin control document has an unsupported version")
        controls_raw = raw.get("account_controls")
        audits_raw = raw.get("admin_audit_events")
        if not isinstance(controls_raw, dict) or not isinstance(audits_raw, list):
            raise ValueError("Admin control document has an invalid shape")
        controls: dict[str, AccountControl] = {}
        for user_id, record in controls_raw.items():
            if not isinstance(user_id, str) or not isinstance(record, dict):
                raise ValueError("Persisted account control is invalid")
            controls[user_id] = _control_from_record(user_id, record)
        if not all(isinstance(record, dict) for record in audits_raw):
            raise ValueError("Persisted admin audit event is invalid")
        return controls, [_audit_from_record(record) for record in audits_raw]

    def _write_document(
        self,
        controls: dict[str, AccountControl],
        audits: list[AdminAuditEvent],
    ) -> None:
        document = {
            "version": 1,
            "account_controls": {
                user_id: _control_to_record(control) for user_id, control in controls.items()
            },
            "admin_audit_events": [_audit_to_record(event) for event in audits],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
            temporary_path = None
            directory_fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get_control(self, user_id: str) -> AccountControl:
        with self._lock, json_list_lock(self._path):
            controls, _ = self._read_document()
        return controls.get(user_id, AccountControl(user_id=user_id, status="active"))

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

        with self._lock, json_list_lock(self._path):
            controls, audits = self._read_document()
            current = controls.get(
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
            controls[target_user_id] = control
            audits.append(event)
            self._write_document(controls, audits)
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
        with self._lock, json_list_lock(self._path):
            _, audits = self._read_document()
        matching = sorted(
            (
                event
                for event in audits
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
