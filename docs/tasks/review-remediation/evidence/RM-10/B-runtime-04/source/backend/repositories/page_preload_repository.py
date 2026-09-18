from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urldefrag

from core.ids import generate_uuid7
from storage.json_list_store import json_list_lock, read_json_list, write_json_list

_PRELOAD_RECORD_LOCK = threading.RLock()
_CONTENT_HANDOFF_SECONDS = 300


class PreloadOperationConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class PreloadCreationResult:
    record: dict[str, Any]
    created: bool


def normalize_page_url(page_url: str) -> str:
    normalized, _ = urldefrag(page_url.strip())
    return normalized.rstrip("/")


class PagePreloadRepository(Protocol):
    def create_if_absent(
        self, user_id: str, record: dict[str, Any], *, now: datetime | None = None
    ) -> PreloadCreationResult: ...

    def mark_content_available(self, user_id: str, preload_id: str, handoff_token: str) -> bool: ...

    def fail_content_handoff(
        self, user_id: str, preload_id: str, handoff_token: str, error: str
    ) -> bool: ...

    def claim_content_handoff(
        self, user_id: str, record: dict[str, Any], *, now: datetime | None = None
    ) -> PreloadCreationResult: ...
    def get_by_page_url(self, user_id: str, page_url: str) -> dict[str, Any] | None: ...

    def get_by_id(self, user_id: str, preload_id: str) -> dict[str, Any] | None: ...

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]: ...

    def save(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        make_latest: bool = True,
    ) -> dict[str, Any]: ...

    def mark_enqueue_submitting(self, user_id: str, preload_id: str) -> bool: ...

    def confirm_enqueued(self, user_id: str, preload_id: str) -> bool: ...

    def claim_processing(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        *,
        lease_id: str | None = None,
        now: datetime | None = None,
        lease_expires_at: datetime | None = None,
    ) -> dict[str, Any] | None: ...

    def finish_processing(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        record: dict[str, Any],
        *,
        lease_id: str | None = None,
        expected_status: str = "running",
    ) -> bool: ...

    def renew_processing_lease(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        lease_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool: ...


class PreloadResultTooLarge(RuntimeError):
    pass


class JsonPagePreloadRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    @staticmethod
    def _find(
        records: list[dict[str, Any]], user_id: str, preload_id: str
    ) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in records
                if item.get("user_id") == user_id and item.get("id") == preload_id
            ),
            None,
        )

    def _save_locked(
        self,
        records: list[dict[str, Any]],
        user_id: str,
        record: dict[str, Any],
        *,
        make_latest: bool,
    ) -> dict[str, Any]:
        stored = dict(record)
        stored["user_id"] = user_id
        normalized_url = normalize_page_url(stored.get("page_url", ""))
        stored["page_url"] = normalized_url
        current = self._find(records, user_id, str(stored.get("id") or ""))
        if make_latest:
            for item in records:
                if (
                    item.get("user_id") == user_id
                    and normalize_page_url(item.get("page_url", "")) == normalized_url
                ):
                    item["is_latest"] = False
            stored["is_latest"] = True
        elif current is not None:
            stored["is_latest"] = bool(current.get("is_latest"))
        records[:] = [
            item
            for item in records
            if not (item.get("user_id") == user_id and item.get("id") == stored.get("id"))
        ]
        records.insert(0, stored)
        write_json_list(self._path, records)
        return stored

    def get_by_page_url(self, user_id: str, page_url: str) -> dict[str, Any] | None:
        normalized = normalize_page_url(page_url)
        fallback = None
        for record in read_json_list(self._path):
            if record.get("user_id") != user_id:
                continue
            if normalize_page_url(record.get("page_url", "")) == normalized:
                if record.get("is_latest") is True:
                    return record
                if fallback is None:
                    fallback = record
        return fallback

    def get_by_id(self, user_id: str, preload_id: str) -> dict[str, Any] | None:
        for record in read_json_list(self._path):
            if record.get("user_id") == user_id and record.get("id") == preload_id:
                return record
        return None

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        all_records = [
            record for record in read_json_list(self._path) if record.get("user_id") == user_id
        ]
        indexed_urls = {
            normalize_page_url(record.get("page_url", ""))
            for record in all_records
            if record.get("is_latest") is True
        }
        records = [
            record
            for record in all_records
            if record.get("is_latest") is True
            or (
                "is_latest" not in record
                and normalize_page_url(record.get("page_url", "")) not in indexed_urls
            )
        ]
        records.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
        return records

    def save(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        make_latest: bool = True,
    ) -> dict[str, Any]:
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            return self._save_locked(
                read_json_list(self._path), user_id, record, make_latest=make_latest
            )

    def create_if_absent(
        self, user_id: str, record: dict[str, Any], *, now: datetime | None = None
    ) -> PreloadCreationResult:
        preload_id = str(record.get("id") or "")
        if not preload_id:
            raise PreloadOperationConflict("Preload operation identity is required.")
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            existing = self._find(records, user_id, preload_id)
            if existing is not None:
                _require_matching_preload_identity(existing, record)
                return PreloadCreationResult(record=existing, created=False)
            moment = (now or datetime.now(UTC)).astimezone(UTC)
            pending = {
                **record,
                "id": preload_id,
                "status": "content_pending",
                "worker_execution_started": False,
                "content_handoff_token": generate_uuid7(),
                "content_handoff_expires_at": (
                    moment + timedelta(seconds=_CONTENT_HANDOFF_SECONDS)
                ).isoformat(),
            }
            return PreloadCreationResult(
                record=self._save_locked(records, user_id, pending, make_latest=True),
                created=True,
            )

    def mark_content_available(self, user_id: str, preload_id: str, handoff_token: str) -> bool:
        return self._transition_content_handoff(
            user_id, preload_id, handoff_token, status="processing", error=None
        )

    def fail_content_handoff(
        self, user_id: str, preload_id: str, handoff_token: str, error: str
    ) -> bool:
        return self._transition_content_handoff(
            user_id, preload_id, handoff_token, status="failed_pending_release", error=error
        )

    def _transition_content_handoff(
        self, user_id: str, preload_id: str, handoff_token: str, *, status: str, error: str | None
    ) -> bool:
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            current = self._find(records, user_id, preload_id)
            is_pending = current is not None and current.get("status") == "content_pending"
            is_unclaimed_processing = (
                current is not None
                and current.get("status") == "processing"
                and not current.get("lease_id")
            )
            if (
                not (is_pending or (error is not None and is_unclaimed_processing))
                or current.get("content_handoff_token") != handoff_token
                or not _handoff_is_current(current, datetime.now(UTC))
            ):
                return False
            updated = {**current, "status": status}
            if error is not None:
                updated["error"] = error
            self._save_locked(records, user_id, updated, make_latest=False)
            return True

    def claim_content_handoff(
        self, user_id: str, record: dict[str, Any], *, now: datetime | None = None
    ) -> PreloadCreationResult:
        preload_id = str(record.get("id") or "")
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            current = self._find(records, user_id, preload_id)
            if current is None:
                raise PreloadOperationConflict("Preload handoff does not exist.")
            _require_matching_preload_identity(current, record)
            if current.get("status") != "content_pending" or _handoff_is_current(current, moment):
                return PreloadCreationResult(record=current, created=False)
            claimed = {
                **current,
                "content_handoff_token": generate_uuid7(),
                "content_handoff_expires_at": (
                    moment + timedelta(seconds=_CONTENT_HANDOFF_SECONDS)
                ).isoformat(),
            }
            return PreloadCreationResult(
                record=self._save_locked(records, user_id, claimed, make_latest=False),
                created=True,
            )

    def mark_enqueue_submitting(self, user_id: str, preload_id: str) -> bool:
        return self._transition_enqueue(
            user_id,
            preload_id,
            expected_states={"pending", "queued_unconfirmed"},
            required_status="processing",
            enqueue_state="queued_unconfirmed",
            submitted=True,
        )

    def confirm_enqueued(self, user_id: str, preload_id: str) -> bool:
        return self._transition_enqueue(
            user_id,
            preload_id,
            expected_states={"queued_unconfirmed", "queued"},
            required_status=None,
            enqueue_state="queued",
            submitted=True,
        )

    def _transition_enqueue(
        self,
        user_id: str,
        preload_id: str,
        *,
        expected_states: set[str],
        required_status: str | None,
        enqueue_state: str,
        submitted: bool,
    ) -> bool:
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            current = self._find(records, user_id, preload_id)
            if (
                not current
                or (required_status is not None and current.get("status") != required_status)
                or (
                    required_status is None
                    and current.get("status")
                    in {"content_pending", "failed", "failed_pending_release"}
                )
                or current.get("enqueue_state") not in expected_states
            ):
                return False
            updated = dict(current)
            updated["enqueue_state"] = enqueue_state
            updated["submitted"] = submitted
            self._save_locked(records, user_id, updated, make_latest=False)
            return True

    def claim_processing(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        *,
        lease_id: str | None = None,
        now: datetime | None = None,
        lease_expires_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            record = self._find(records, user_id, preload_id)
            if (
                not record
                or record.get("learner_profile_fingerprint") != learner_profile_fingerprint
            ):
                return None
            status = record.get("status")
            moment = now or datetime.now(UTC)
            lease_expiry = _parse_datetime(record.get("lease_expires_at"))
            reclaimable = (
                status == "running" and lease_expiry is not None and lease_expiry <= moment
            )
            if status != "processing" and not reclaimable:
                return None
            claimed = dict(record)
            claimed["status"] = "running"
            claimed["worker_execution_started"] = True
            if lease_id:
                claimed["lease_id"] = lease_id
                claimed["lease_expires_at"] = (
                    (lease_expires_at or moment).astimezone(UTC).isoformat()
                )
                claimed["attempt_count"] = int(record.get("attempt_count") or 0) + 1
            self._save_locked(records, user_id, claimed, make_latest=False)
            return {
                **claimed,
                "_claimed_from_unstarted_processing": (
                    status == "processing"
                    and not record.get("lease_id")
                    and record.get("worker_execution_started") is False
                ),
            }

    def finish_processing(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        record: dict[str, Any],
        *,
        lease_id: str | None = None,
        expected_status: str = "running",
    ) -> bool:
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            current = self._find(records, user_id, preload_id)
            if (
                not current
                or current.get("status") != expected_status
                or current.get("learner_profile_fingerprint") != learner_profile_fingerprint
                or (lease_id is not None and current.get("lease_id") != lease_id)
            ):
                return False
            self._save_locked(records, user_id, record, make_latest=False)
            return True

    def renew_processing_lease(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        lease_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        with _PRELOAD_RECORD_LOCK, json_list_lock(self._path):
            records = read_json_list(self._path)
            current = self._find(records, user_id, preload_id)
            if (
                not current
                or current.get("status") != "running"
                or current.get("learner_profile_fingerprint") != learner_profile_fingerprint
                or current.get("lease_id") != lease_id
            ):
                return False
            renewed = dict(current)
            renewed["lease_expires_at"] = lease_expires_at.astimezone(UTC).isoformat()
            self._save_locked(records, user_id, renewed, make_latest=False)
            return True


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _handoff_is_current(record: dict[str, Any], now: datetime) -> bool:
    expiry = _parse_datetime(record.get("content_handoff_expires_at"))
    return expiry is not None and expiry > now


def _require_matching_preload_identity(existing: dict[str, Any], requested: dict[str, Any]) -> None:
    identity = (
        "id",
        "operation_id",
        "payload_hash",
        "learner_profile_fingerprint",
    )
    if any(existing.get(field) != requested.get(field) for field in identity) or (
        normalize_page_url(existing.get("page_url", ""))
        != normalize_page_url(requested.get("page_url", ""))
    ):
        raise PreloadOperationConflict("Preload operation identity conflicts.")
