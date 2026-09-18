from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from core.ids import generate_uuid7
from storage.dynamodb_keys import (
    PRELOAD_ID_SK_PREFIX,
    PRELOAD_SK_PREFIX,
    preload_id_sk,
    preload_sk,
    user_pk,
)
from storage.dynamodb_store import DynamoDbStore

from repositories.page_preload_repository import (
    PreloadCreationResult,
    PreloadOperationConflict,
    PreloadResultTooLarge,
    _handoff_is_current,
    _parse_datetime,
    _require_matching_preload_identity,
    normalize_page_url,
)

_SERIALIZER = TypeSerializer()
_CONTENT_HANDOFF_SECONDS = 300


class DynamoPagePreloadRepository:
    def __init__(self, store: DynamoDbStore) -> None:
        self._store = store

    def get_by_page_url(self, user_id: str, page_url: str) -> dict[str, Any] | None:
        normalized = normalize_page_url(page_url)
        index = self._store.get_document(
            user_pk(user_id), preload_sk(normalized), consistent_read=True
        )
        if index and index.get("preload_id"):
            record = self.get_by_id(user_id, str(index["preload_id"]))
        else:
            record = index
        if not record or record.get("user_id") != user_id:
            return None
        return record

    def get_by_id(self, user_id: str, preload_id: str) -> dict[str, Any] | None:
        direct = self._store.get_document(
            user_pk(user_id), preload_id_sk(preload_id), consistent_read=True
        )
        if direct and direct.get("user_id") == user_id:
            return direct
        for record in self._store.query_by_pk(user_pk(user_id), sk_prefix=PRELOAD_SK_PREFIX):
            if record.get("id") == preload_id and record.get("user_id") == user_id:
                return record
        return None

    def create_if_absent(
        self, user_id: str, record: dict[str, Any], *, now: datetime | None = None
    ) -> PreloadCreationResult:
        preload_id = str(record.get("id") or "")
        if not preload_id:
            raise PreloadOperationConflict("Preload operation identity is required.")
        existing = self.get_by_id(user_id, preload_id)
        if existing is not None:
            _require_matching_preload_identity(existing, record)
            return PreloadCreationResult(record=existing, created=False)
        normalized_url = normalize_page_url(record.get("page_url", ""))
        observed_index = self._store.get_document(
            user_pk(user_id), preload_sk(normalized_url), consistent_read=True
        )
        legacy_materialization: dict[str, Any] | None = None
        if observed_index is not None:
            predecessor_id = str(observed_index.get("preload_id") or observed_index.get("id") or "")
            if not predecessor_id:
                raise PreloadOperationConflict(
                    "Preload page index cannot establish a predecessor operation identity."
                )
            predecessor = self._store.get_document(
                user_pk(user_id), preload_id_sk(predecessor_id), consistent_read=True
            )
            if predecessor is None:
                if observed_index.get("preload_id"):
                    raise PreloadOperationConflict(
                        "Legacy preload page index cannot establish a matching operation identity."
                    )
                self._validate_legacy_predecessor(user_id, normalized_url, observed_index)
                if predecessor_id == preload_id:
                    _require_matching_preload_identity(observed_index, record)
                    return PreloadCreationResult(record=observed_index, created=False)
                legacy_materialization = observed_index
            elif (
                predecessor.get("user_id") != user_id
                or predecessor.get("id") != predecessor_id
                or normalize_page_url(predecessor.get("page_url", "")) != normalized_url
            ):
                raise PreloadOperationConflict("Preload page index predecessor conflicts.")
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        pending = {
            **record,
            "id": preload_id,
            "user_id": user_id,
            "page_url": normalized_url,
            "status": "content_pending",
            "content_handoff_token": generate_uuid7(),
            "content_handoff_expires_at": (
                moment + timedelta(seconds=_CONTENT_HANDOFF_SECONDS)
            ).isoformat(),
        }
        self._validate_size(pending)
        transaction = [
            self._conditional_put_item(
                user_pk(user_id),
                preload_id_sk(preload_id),
                pending,
                self._identity_attributes(pending),
            ),
            self._conditional_put_item(
                user_pk(user_id),
                preload_sk(normalized_url),
                {"user_id": user_id, "page_url": normalized_url, "preload_id": preload_id},
                None,
                expected_document=observed_index,
            ),
        ]
        if legacy_materialization is not None:
            transaction.append(
                self._conditional_put_item(
                    user_pk(user_id),
                    preload_id_sk(str(legacy_materialization["id"])),
                    legacy_materialization,
                    self._identity_attributes(legacy_materialization),
                )
            )
        try:
            self._store.transact_write(transaction)
        except ClientError as exc:
            if not _is_conditional_create_conflict(exc):
                raise
            winner = self.get_by_id(user_id, preload_id)
            if winner is not None:
                _require_matching_preload_identity(winner, record)
                return PreloadCreationResult(record=winner, created=False)
            current_index = self._store.get_document(
                user_pk(user_id), preload_sk(normalized_url), consistent_read=True
            )
            if current_index != observed_index:
                raise PreloadOperationConflict(
                    "Preload page index changed during creation."
                ) from exc
            raise PreloadOperationConflict(
                "Conditional preload creation did not establish a known winner."
            ) from exc
        return PreloadCreationResult(record=pending, created=True)

    def mark_content_available(self, user_id: str, preload_id: str, handoff_token: str) -> bool:
        return self._transition_content_handoff(
            user_id, preload_id, handoff_token, "processing", None
        )

    def fail_content_handoff(
        self, user_id: str, preload_id: str, handoff_token: str, error: str
    ) -> bool:
        return self._transition_content_handoff(
            user_id, preload_id, handoff_token, "failed_pending_release", error
        )

    def claim_content_handoff(
        self, user_id: str, record: dict[str, Any], *, now: datetime | None = None
    ) -> PreloadCreationResult:
        preload_id = str(record.get("id") or "")
        current = self.get_by_id(user_id, preload_id)
        if current is None:
            raise PreloadOperationConflict("Preload handoff does not exist.")
        _require_matching_preload_identity(current, record)
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        if current.get("status") != "content_pending" or _handoff_is_current(current, moment):
            return PreloadCreationResult(record=current, created=False)
        claimed = {
            **current,
            "content_handoff_token": generate_uuid7(),
            "content_handoff_expires_at": (
                moment + timedelta(seconds=_CONTENT_HANDOFF_SECONDS)
            ).isoformat(),
        }
        if not self._store.conditional_put_document(
            user_pk(user_id),
            preload_id_sk(preload_id),
            claimed,
            extra_attributes=self._identity_attributes(claimed),
            expected_attributes=self._identity_attributes(current),
        ):
            return PreloadCreationResult(
                record=self.get_by_id(user_id, preload_id) or current,
                created=False,
            )
        return PreloadCreationResult(record=claimed, created=True)

    def _transition_content_handoff(
        self, user_id: str, preload_id: str, handoff_token: str, status: str, error: str | None
    ) -> bool:
        current = self.get_by_id(user_id, preload_id)
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
        return self._store.conditional_put_document(
            user_pk(user_id),
            preload_id_sk(preload_id),
            updated,
            extra_attributes=self._identity_attributes(updated),
            expected_attributes=self._identity_attributes(current),
        )

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        id_records = self._store.query_by_pk(user_pk(user_id), sk_prefix=PRELOAD_ID_SK_PREFIX)
        by_id = {str(record.get("id") or ""): record for record in id_records}
        records = []
        for entry in self._store.query_by_pk(user_pk(user_id), sk_prefix=PRELOAD_SK_PREFIX):
            if entry.get("preload_id"):
                record = by_id.get(str(entry["preload_id"]))
                if record:
                    records.append(record)
            elif entry.get("id") and entry.get("user_id") == user_id:
                records.append(entry)
        records.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
        return records

    def save(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        make_latest: bool = True,
    ) -> dict[str, Any]:
        stored = dict(record)
        stored["user_id"] = user_id
        normalized_url = normalize_page_url(stored.get("page_url", ""))
        stored["page_url"] = normalized_url
        self._validate_size(stored)
        if make_latest:
            self._store.put_documents_atomically(
                [
                    (
                        user_pk(user_id),
                        preload_id_sk(str(stored.get("id") or "")),
                        stored,
                        self._identity_attributes(stored),
                    ),
                    (
                        user_pk(user_id),
                        preload_sk(normalized_url),
                        {
                            "user_id": user_id,
                            "page_url": normalized_url,
                            "preload_id": stored.get("id"),
                        },
                        None,
                    ),
                ]
            )
        else:
            self._store.put_document(
                user_pk(user_id),
                preload_id_sk(str(stored.get("id") or "")),
                stored,
                extra_attributes=self._identity_attributes(stored),
            )
        return stored

    def mark_enqueue_submitting(self, user_id: str, preload_id: str) -> bool:
        return self._transition_enqueue(
            user_id,
            preload_id,
            expected_states={"pending", "queued_unconfirmed"},
            enqueue_state="queued_unconfirmed",
            submitted=True,
        )

    def confirm_enqueued(self, user_id: str, preload_id: str) -> bool:
        return self._transition_enqueue(
            user_id,
            preload_id,
            expected_states={"queued_unconfirmed", "queued"},
            enqueue_state="queued",
            submitted=True,
        )

    def _transition_enqueue(
        self,
        user_id: str,
        preload_id: str,
        *,
        expected_states: set[str],
        enqueue_state: str,
        submitted: bool,
    ) -> bool:
        for _attempt in range(4):
            current = self.get_by_id(user_id, preload_id)
            if (
                not current
                or current.get("status") in {"content_pending", "failed"}
                or current.get("enqueue_state") not in expected_states
            ):
                return False
            updated = dict(current)
            updated["enqueue_state"] = enqueue_state
            updated["submitted"] = submitted
            self._validate_size(updated)
            if self._store.conditional_put_document(
                user_pk(user_id),
                preload_id_sk(preload_id),
                updated,
                extra_attributes=self._identity_attributes(updated),
                expected_attributes=self._identity_attributes(current),
            ):
                return True
        return False

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
        record = self.get_by_id(user_id, preload_id)
        if not record or record.get("page_url") is None:
            return None
        if (
            self._store.get_document(
                user_pk(user_id), preload_id_sk(preload_id), consistent_read=True
            )
            is None
        ):
            self._store.put_document_if_absent(
                user_pk(user_id),
                preload_id_sk(preload_id),
                record,
                extra_attributes=self._identity_attributes(record),
            )
            record = self.get_by_id(user_id, preload_id) or record
        moment = now or datetime.now(UTC)
        status = record.get("status")
        current_expiry = _parse_datetime(record.get("lease_expires_at"))
        reclaimable = (
            status == "running" and current_expiry is not None and current_expiry <= moment
        )
        if status != "processing" and not reclaimable:
            return None
        claimed = dict(record)
        claimed["status"] = "running"
        if lease_id:
            claimed["lease_id"] = lease_id
            claimed["lease_expires_at"] = (lease_expires_at or moment).astimezone(UTC).isoformat()
            claimed["attempt_count"] = int(record.get("attempt_count") or 0) + 1
        expected = {
            "preload_id": preload_id,
            "learner_profile_fingerprint": learner_profile_fingerprint,
            "status": status,
        }
        if status == "running":
            expected["lease_id"] = str(record.get("lease_id") or "")
            expected["lease_expires_at"] = str(record.get("lease_expires_at") or "")
        if not self._store.conditional_put_document(
            user_pk(user_id),
            preload_id_sk(preload_id),
            claimed,
            extra_attributes=self._identity_attributes(claimed),
            expected_attributes=expected,
        ):
            return None
        return claimed

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
        stored = dict(record)
        stored["user_id"] = user_id
        stored["page_url"] = normalize_page_url(stored.get("page_url", ""))
        self._validate_size(stored)
        expected = {
            "preload_id": preload_id,
            "learner_profile_fingerprint": learner_profile_fingerprint,
            "status": expected_status,
        }
        if lease_id is not None:
            expected["lease_id"] = lease_id
        return self._store.conditional_put_document(
            user_pk(user_id),
            preload_id_sk(preload_id),
            stored,
            extra_attributes=self._identity_attributes(stored),
            expected_attributes=expected,
        )

    def renew_processing_lease(
        self,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        lease_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        current = self.get_by_id(user_id, preload_id)
        if not current:
            return False
        renewed = dict(current)
        renewed["lease_expires_at"] = lease_expires_at.astimezone(UTC).isoformat()
        return self._store.conditional_put_document(
            user_pk(user_id),
            preload_id_sk(preload_id),
            renewed,
            extra_attributes=self._identity_attributes(renewed),
            expected_attributes={
                "preload_id": preload_id,
                "learner_profile_fingerprint": learner_profile_fingerprint,
                "status": "running",
                "lease_id": lease_id,
                "lease_expires_at": str(current.get("lease_expires_at") or ""),
            },
        )

    @staticmethod
    def _identity_attributes(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "preload_id": str(record.get("id") or ""),
            "learner_profile_fingerprint": str(record.get("learner_profile_fingerprint") or ""),
            "status": str(record.get("status") or ""),
            "lease_id": str(record.get("lease_id") or ""),
            "lease_expires_at": str(record.get("lease_expires_at") or ""),
            "enqueue_state": str(record.get("enqueue_state") or ""),
            "submitted": bool(record.get("submitted")),
            "content_handoff_token": str(record.get("content_handoff_token") or ""),
            "content_handoff_expires_at": str(record.get("content_handoff_expires_at") or ""),
        }

    def _conditional_put_item(
        self,
        pk: str,
        sk: str,
        document: dict[str, Any],
        extra_attributes: dict[str, Any] | None,
        *,
        expected_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = {
            "pk": pk,
            "sk": sk,
            "document": json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            **(extra_attributes or {}),
        }
        put: dict[str, Any] = {
            "TableName": self._store.table_name,
            "Item": {key: _SERIALIZER.serialize(value) for key, value in item.items()},
            "ConditionExpression": "attribute_not_exists(pk)",
        }
        if expected_document is not None:
            put["ConditionExpression"] = "#document = :expected_document"
            put["ExpressionAttributeNames"] = {"#document": "document"}
            put["ExpressionAttributeValues"] = {
                ":expected_document": _SERIALIZER.serialize(
                    json.dumps(expected_document, ensure_ascii=False, separators=(",", ":"))
                )
            }
        return {"Put": put}

    def _validate_legacy_predecessor(
        self, user_id: str, normalized_url: str, record: dict[str, Any]
    ) -> None:
        if (
            record.get("user_id") != user_id
            or normalize_page_url(record.get("page_url", "")) != normalized_url
            or not record.get("id")
        ):
            raise PreloadOperationConflict("Legacy preload page record conflicts.")
        self._validate_size(record)

    @staticmethod
    def _validate_size(record: dict[str, Any]) -> None:
        ceiling = min(
            380000,
            max(
                1,
                int(os.getenv("DYNAMODB_PRELOAD_MAX_BYTES", "350000")),
            ),
        )
        size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > ceiling:
            raise PreloadResultTooLarge(
                f"Preload result exceeds serialized size ceiling ({size}>{ceiling})"
            )


def _is_conditional_create_conflict(exc: ClientError) -> bool:
    if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    reasons = exc.response.get("CancellationReasons")
    if not isinstance(reasons, list) or not reasons:
        return False
    if not all(
        isinstance(reason, dict) and reason.get("Code") in {"None", "ConditionalCheckFailed"}
        for reason in reasons
    ):
        return False
    return any(reason["Code"] == "ConditionalCheckFailed" for reason in reasons)
