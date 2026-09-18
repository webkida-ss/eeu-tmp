from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from storage.dynamodb_keys import (
    SK_SUBSCRIPTION,
    USAGE_RESULT_TTL_ATTRIBUTE,
    stripe_customer_pk,
    usage_event_sk,
    usage_execution_sk,
    usage_operation_sk,
    usage_result_sk,
    usage_sk,
    user_pk,
)
from storage.dynamodb_store import DOCUMENT_ATTRIBUTE, DynamoDbStore

from repositories.usage_repository import (
    COUNTER_FIELDS,
    USAGE_FIELDS,
    ExecutionClaimStatus,
    ShadowSettlementOutcome,
    UsageFinalizeRequest,
    UsageOperation,
    UsageOperationConflict,
    UsageOperationNotFound,
    UsageOperationStateError,
    UsageRepositoryError,
    UsageReservationRequest,
    _apply_amounts,
    _check_admission,
    _conservative_finalize_request,
    _event_record,
    _finalize_request_from_evidence,
    _finalize_request_from_result,
    _operation_from_record,
    _operation_to_record,
    _parse_datetime,
    _promote_dispatch_evidence,
    _ratchet_limits,
    _reconcile_compatibility_counters,
    _retain_processing_allowance,
    _shadow_pending_values,
    _subtract_reserved,
    _validate_add_amounts,
    _validate_result_size,
    empty_usage,
)

_SERIALIZER = TypeSerializer()


class DynamoUsageRepository:
    """DynamoDB-backed idempotent usage reservation lifecycle."""

    def __init__(self, store: DynamoDbStore) -> None:
        self._store = store

    def get_month(self, user_id: str, month: str) -> dict[str, Any]:
        record = self._load_month(user_id, month)
        record.pop("version", None)
        return record

    def add(self, user_id: str, month: str, **amounts: int) -> dict[str, Any]:
        _validate_add_amounts(amounts)
        for _attempt in range(4):
            current = self._load_month(user_id, month)
            expected_version = int(current.get("version") or 0)
            _apply_amounts(current, amounts)
            current["version"] = expected_version + 1
            try:
                self._store.transact_write([self._aggregate_put(current, expected_version)])
                current.pop("version", None)
                return current
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        raise UsageRepositoryError("Usage compatibility add transaction conflicted")

    def reserve(self, request: UsageReservationRequest) -> UsageOperation:
        if request.accounting_mode != "enforced":
            raise UsageOperationStateError("Shadow operations require start_shadow")
        existing = self.get_operation(request.user_id, request.operation_id)
        if existing is not None:
            return self._idempotent_reserve(existing, request)

        for _attempt in range(4):
            month = self._load_month(request.user_id, request.month)
            expected_version = int(month.get("version") or 0)
            _ratchet_limits(month, request)
            _check_admission(month, request)
            month["reserved_articles"] += request.articles
            month["reserved_chats"] += request.chats
            month["reserved_cost_micro_usd"] += request.cost_micro_usd
            month["version"] = expected_version + 1
            operation = UsageOperation.reserved(request)
            transaction = [
                self._aggregate_put(month, expected_version),
                self._operation_put(operation, create=True),
                self._event_put(operation, "reserve"),
            ]
            try:
                self._store.transact_write(transaction)
                return operation
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
                existing = self.get_operation(request.user_id, request.operation_id)
                if existing is not None:
                    return self._idempotent_reserve(existing, request)
                latest = self._load_month(request.user_id, request.month)
                _ratchet_limits(latest, request)
                _check_admission(latest, request)
        raise UsageRepositoryError("Usage reservation transaction conflicted")

    def start_shadow(self, request: UsageReservationRequest) -> UsageOperation:
        if request.accounting_mode != "shadow":
            raise UsageOperationStateError("Shadow operation mode is required")
        existing = self.get_operation(request.user_id, request.operation_id)
        if existing is not None:
            if (
                existing.accounting_mode != "shadow"
                or existing.payload_hash != request.payload_hash
            ):
                raise UsageOperationConflict("Shadow operation identity conflicts")
            return existing
        for _attempt in range(4):
            month = self._load_month(request.user_id, request.month)
            expected_version = int(month.get("version") or 0)
            _retain_processing_allowance(month, request)
            month["version"] = expected_version + 1
            operation = UsageOperation.reserved(request)
            try:
                self._store.transact_write(
                    [
                        self._aggregate_put(month, expected_version),
                        self._operation_put(operation, create=True),
                        self._event_put(operation, "shadow_start"),
                    ]
                )
                return operation
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
            existing = self.get_operation(request.user_id, request.operation_id)
            if existing is not None:
                if (
                    existing.accounting_mode != "shadow"
                    or existing.payload_hash != request.payload_hash
                ):
                    raise UsageOperationConflict("Shadow operation identity conflicts")
                return existing
        raise UsageRepositoryError("Shadow operation transaction conflicted")

    def prepare_shadow_settlement(
        self,
        user_id: str,
        operation_id: str,
        outcome: ShadowSettlementOutcome,
        *,
        result_ref: str | None = None,
    ) -> UsageOperation:
        if outcome not in ("success", "failed_before_dispatch", "failed_after_dispatch"):
            raise UsageOperationConflict("Shadow settlement outcome is invalid")
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if operation is None:
                raise UsageOperationNotFound(operation_id)
            if operation.accounting_mode != "shadow":
                raise UsageOperationStateError("Operation is not shadow accounted")
            if operation.state == "finalized":
                if operation.shadow_outcome != outcome or operation.result_ref != result_ref:
                    raise UsageOperationConflict("Shadow settlement outcome conflicts")
                return operation
            prepared = operation.with_shadow_pending(
                **_shadow_pending_values(operation, outcome, result_ref)
            )
            if prepared == operation:
                return operation
            try:
                self._store.transact_write(
                    [
                        self._operation_put(
                            prepared,
                            expected_state="reserved",
                            expected_dispatch_evidence_version=operation.dispatch_evidence_version,
                        ),
                        self._event_put(prepared, "shadow_prepare"),
                    ]
                )
                return prepared
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        raise UsageRepositoryError("Shadow settlement preparation conflicted")

    def settle_shadow(self, user_id: str, operation_id: str) -> UsageOperation:
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if operation is None:
                raise UsageOperationNotFound(operation_id)
            if operation.accounting_mode != "shadow":
                raise UsageOperationStateError("Operation is not shadow accounted")
            if operation.state == "finalized":
                return operation
            if not operation.shadow_pending_outcome:
                raise UsageOperationStateError("Shadow settlement is not prepared")
            month = self._load_month(operation.user_id, operation.month)
            expected_version = int(month.get("version") or 0)
            usage = operation.shadow_pending_usage or {}
            _apply_amounts(
                month,
                {
                    "articles": int(usage.get("actual_articles") or 0),
                    "tokens": int(usage.get("total_tokens") or 0),
                    "shadow_cost_micro_usd": int(usage.get("actual_cost_micro_usd") or 0),
                },
            )
            month["version"] = expected_version + 1
            settled = operation.settled_shadow()
            try:
                self._store.transact_write(
                    [
                        self._aggregate_put(month, expected_version),
                        self._operation_put(
                            settled,
                            expected_state="reserved",
                            expected_dispatch_evidence_version=operation.dispatch_evidence_version,
                        ),
                        self._event_put(settled, "shadow_settle"),
                    ]
                )
                return settled
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        raise UsageRepositoryError("Shadow settlement transaction conflicted")

    def finalize(self, request: UsageFinalizeRequest) -> UsageOperation:
        for _attempt in range(4):
            operation = self.get_operation(request.user_id, request.operation_id)
            if operation is None:
                raise UsageOperationNotFound(request.operation_id)
            if operation.accounting_mode != "enforced":
                raise UsageOperationStateError("Shadow operations require settle_shadow")
            if operation.state == "finalized":
                return operation
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot finalize {operation.state} operation")
            if (
                request.result_ref == f"usage-evidence:{operation.operation_id}"
                or operation.dispatch_evidence_state == "completed"
            ):
                # Recompute after every CAS retry. A completed marker can win
                # between an expired-reclaim read and this transaction; its
                # measured evidence must never be replaced by the old floor.
                request = _finalize_request_from_evidence(operation)

            month = self._load_month(operation.user_id, operation.month)
            expected_version = int(month.get("version") or 0)
            _subtract_reserved(month, operation)
            month["committed_articles"] += operation.reserved_articles
            month["committed_chats"] += operation.reserved_chats
            month["committed_cost_micro_usd"] += request.actual_cost_micro_usd
            month["articles"] += operation.reserved_articles
            month["chats"] += operation.reserved_chats
            month["shadow_cost_micro_usd"] += request.actual_cost_micro_usd
            actual_tokens = request.tokens or request.input_tokens + request.output_tokens
            month["tokens"] += actual_tokens
            month["version"] = expected_version + 1
            finalized = operation.finalized(request, actual_tokens=actual_tokens)
            try:
                self._store.transact_write(
                    [
                        self._aggregate_put(month, expected_version),
                        self._operation_put(
                            finalized,
                            expected_state="reserved",
                            expected_dispatch_evidence_version=(
                                operation.dispatch_evidence_version
                            ),
                            expected_missing_dispatch_evidence=(
                                operation.dispatch_evidence_state == "unknown"
                                and operation.dispatch_evidence_version == 0
                            ),
                        ),
                        self._event_put(finalized, "finalize"),
                    ]
                )
                return finalized
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        latest = self.get_operation(request.user_id, request.operation_id)
        if latest is not None and latest.state == "finalized":
            return latest
        raise UsageRepositoryError("Usage finalization transaction conflicted")

    def release(self, user_id: str, operation_id: str, *, reason: str) -> UsageOperation:
        operation, _transitioned = self._release_transition(user_id, operation_id, reason=reason)
        return operation

    def _release_transition(
        self,
        user_id: str,
        operation_id: str,
        *,
        reason: str,
        expired_before: datetime | None = None,
    ) -> tuple[UsageOperation, bool]:
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if operation is None:
                raise UsageOperationNotFound(operation_id)
            if operation.accounting_mode != "enforced":
                raise UsageOperationStateError("Shadow operations cannot be released")
            if operation.state == "released":
                return operation, False
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot release {operation.state} operation")
            if operation.dispatch_evidence_state != "not_dispatched":
                raise UsageOperationStateError("Cannot release an operation with dispatch evidence")
            if expired_before is not None and operation.expires_at > expired_before:
                return operation, False
            if expired_before is not None:
                execution = (
                    self._store.get_item(
                        user_pk(user_id),
                        usage_execution_sk(operation_id),
                        consistent_read=True,
                    )
                    or {}
                )
                execution_expiry = execution.get("expires_at")
                if execution_expiry and _parse_datetime(str(execution_expiry)) > expired_before:
                    return operation, False

            month = self._load_month(operation.user_id, operation.month)
            expected_version = int(month.get("version") or 0)
            _subtract_reserved(month, operation)
            month["version"] = expected_version + 1
            released = operation.released(reason)
            try:
                self._store.transact_write(
                    [
                        self._aggregate_put(month, expected_version),
                        self._operation_put(
                            released,
                            expected_state="reserved",
                            expected_expires_at=(
                                operation.expires_at if expired_before is not None else None
                            ),
                            expected_dispatch_evidence_version=(
                                operation.dispatch_evidence_version
                            ),
                            expected_missing_dispatch_evidence=(
                                operation.dispatch_evidence_state == "unknown"
                                and operation.dispatch_evidence_version == 0
                            ),
                        ),
                        self._event_put(released, "release", reason=reason),
                        *(
                            [self._expired_execution_check(user_id, operation_id, expired_before)]
                            if expired_before is not None
                            else []
                        ),
                    ]
                )
                return released, True
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        latest = self.get_operation(user_id, operation_id)
        if latest is not None and latest.state == "released":
            return latest, False
        raise UsageRepositoryError("Usage release transaction conflicted")

    def get_operation(self, user_id: str, operation_id: str) -> UsageOperation | None:
        item = self._store.get_item(
            user_pk(user_id),
            usage_operation_sk(operation_id),
            consistent_read=True,
        )
        if not item or not isinstance(item.get(DOCUMENT_ATTRIBUTE), str):
            return None
        record = json.loads(item[DOCUMENT_ATTRIBUTE])
        return _operation_from_record(record) if record is not None else None

    def save_result(
        self, user_id: str, operation_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        self._persist_dispatch_evidence(user_id, operation_id, result)
        pk = user_pk(user_id)
        sk = usage_result_sk(operation_id)
        expires_at = datetime.now(UTC) + timedelta(
            seconds=max(
                1,
                int(os.getenv("SYNC_RESULT_TTL_SECONDS", "86400")),
            )
        )
        stored = {
            **result,
            "expires_at": expires_at.isoformat(),
        }
        _validate_result_size(stored)
        if self._store.put_document_if_absent(
            pk,
            sk,
            stored,
            extra_attributes={
                "expires_at": stored["expires_at"],
                USAGE_RESULT_TTL_ATTRIBUTE: int(expires_at.timestamp()),
                "state": str(result.get("state") or "completed"),
            },
        ):
            return result
        existing = self.get_result(user_id, operation_id)
        if (
            existing
            and existing.get("state") == "dispatching"
            and result.get("state") == "completed"
            and self._store.conditional_put_document(
                pk,
                sk,
                stored,
                extra_attributes={
                    "expires_at": stored["expires_at"],
                    USAGE_RESULT_TTL_ATTRIBUTE: int(expires_at.timestamp()),
                    "state": "completed",
                },
                expected_attributes={"state": "dispatching"},
            )
        ):
            return result
        if existing != result:
            raise UsageOperationConflict(f"Operation {operation_id} has a different stored result")
        return result

    def _persist_dispatch_evidence(
        self, user_id: str, operation_id: str, result: dict[str, Any]
    ) -> None:
        """Persist safe dispatch evidence before writing a TTL-private result."""
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if operation is None:
                # Compatibility callers may use result storage without a quota
                # operation. Those records have no durable reservation to fence.
                return
            promoted = _promote_dispatch_evidence(operation, result)
            if promoted == operation:
                return
            try:
                self._store.transact_write(
                    [
                        self._operation_put(
                            promoted,
                            expected_state=operation.state,
                            expected_dispatch_evidence_version=(
                                operation.dispatch_evidence_version
                            ),
                            expected_missing_dispatch_evidence=(
                                operation.dispatch_evidence_state == "unknown"
                                and operation.dispatch_evidence_version == 0
                            ),
                        )
                    ]
                )
                return
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        # Re-read once more to make a stale writer apply the same monotonic
        # validation instead of rebasing a whole stale operation snapshot.
        operation = self.get_operation(user_id, operation_id)
        if operation is None:
            return
        promoted = _promote_dispatch_evidence(operation, result)
        if promoted == operation:
            return
        raise UsageRepositoryError("Dispatch evidence transaction conflicted")

    def get_result(self, user_id: str, operation_id: str) -> dict[str, Any] | None:
        item = self._store.get_item(
            user_pk(user_id),
            usage_result_sk(operation_id),
            consistent_read=True,
        )
        if not item or not isinstance(item.get(DOCUMENT_ATTRIBUTE), str):
            return None
        parsed = json.loads(item[DOCUMENT_ATTRIBUTE])
        if not isinstance(parsed, dict):
            return None
        expires_at = parsed.pop("expires_at", None)
        if expires_at and _parse_datetime(expires_at) <= datetime.now(UTC):
            self._store.delete(user_pk(user_id), usage_result_sk(operation_id))
            return None
        return parsed

    def renew(self, user_id: str, operation_id: str, expires_at: datetime) -> UsageOperation:
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if operation is None:
                raise UsageOperationNotFound(operation_id)
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot renew {operation.state} operation")
            renewed = operation.renewed(expires_at)
            try:
                self._store.transact_write(
                    [
                        self._operation_put(
                            renewed,
                            expected_state="reserved",
                            expected_expires_at=operation.expires_at,
                            expected_dispatch_evidence_version=(
                                operation.dispatch_evidence_version
                            ),
                            expected_missing_dispatch_evidence=(
                                operation.dispatch_evidence_state == "unknown"
                                and operation.dispatch_evidence_version == 0
                            ),
                        )
                    ]
                )
                return renewed
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        latest = self.get_operation(user_id, operation_id)
        if latest is not None and latest.state != "reserved":
            raise UsageOperationStateError(f"Cannot renew {latest.state} operation")
        raise UsageRepositoryError("Usage renewal transaction conflicted")

    def claim_execution(
        self,
        user_id: str,
        operation_id: str,
        claim_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionClaimStatus | None:
        pk = user_pk(user_id)
        sk = usage_execution_sk(operation_id)
        claimed = {
            "user_id": user_id,
            "operation_id": operation_id,
            "claim_id": claim_id,
            "expires_at": expires_at.isoformat(),
        }
        attributes = {
            "claim_id": claim_id,
            "expires_at": expires_at.isoformat(),
        }
        if self._store.put_document_if_absent(pk, sk, claimed, extra_attributes=attributes):
            return "claimed"
        item = self._store.get_item(pk, sk, consistent_read=True) or {}
        current_expiry = _parse_datetime(str(item.get("expires_at") or ""))
        if item.get("claim_id") == claim_id:
            return "owned"
        if current_expiry > now:
            return None
        recovered = self._store.conditional_put_document(
            pk,
            sk,
            claimed,
            extra_attributes=attributes,
            expected_attributes={
                "claim_id": str(item.get("claim_id") or ""),
                "expires_at": str(item.get("expires_at") or ""),
            },
        )
        return "recovered" if recovered else None

    def release_execution(
        self, user_id: str, operation_id: str, claim_id: str, now: datetime
    ) -> bool:
        pk = user_pk(user_id)
        sk = usage_execution_sk(operation_id)
        item = self._store.get_item(pk, sk, consistent_read=True) or {}
        if item.get("claim_id") != claim_id:
            return False
        released = {
            "user_id": user_id,
            "operation_id": operation_id,
            "claim_id": claim_id,
            "expires_at": now.isoformat(),
        }
        return self._store.conditional_put_document(
            pk,
            sk,
            released,
            extra_attributes={
                "claim_id": claim_id,
                "expires_at": now.isoformat(),
            },
            expected_attributes={
                "claim_id": claim_id,
                "expires_at": str(item.get("expires_at") or ""),
            },
        )

    def renew_execution(
        self,
        user_id: str,
        operation_id: str,
        claim_id: str,
        expires_at: datetime,
    ) -> bool:
        pk = user_pk(user_id)
        sk = usage_execution_sk(operation_id)
        item = self._store.get_item(pk, sk, consistent_read=True) or {}
        if item.get("claim_id") != claim_id:
            return False
        renewed = {
            "user_id": user_id,
            "operation_id": operation_id,
            "claim_id": claim_id,
            "expires_at": expires_at.isoformat(),
        }
        return self._store.conditional_put_document(
            pk,
            sk,
            renewed,
            extra_attributes={
                "claim_id": claim_id,
                "expires_at": expires_at.isoformat(),
            },
            expected_attributes={
                "claim_id": claim_id,
                "expires_at": str(item.get("expires_at") or ""),
            },
        )

    def reclaim_expired(self, user_id: str, now: datetime) -> int:
        records = self._store.query_by_pk(user_pk(user_id), sk_prefix="USAGE_OPERATION#")
        reclaimed = 0
        for record in records:
            try:
                expired = (
                    record.get("state") == "reserved"
                    and _parse_datetime(record["expires_at"]) <= now
                )
            except Exception:
                continue
            if expired:
                operation = self.get_operation(user_id, str(record["operation_id"]))
                if operation is None or operation.state != "reserved":
                    continue
                if operation.accounting_mode == "shadow":
                    if self._reclaim_shadow(user_id, operation.operation_id, now):
                        reclaimed += 1
                    continue
                if operation.dispatch_evidence_state != "not_dispatched":
                    if self._reclaim_finalize(user_id, operation.operation_id, now):
                        reclaimed += 1
                    continue
                try:
                    _operation, transitioned = self._release_transition(
                        user_id,
                        record["operation_id"],
                        reason="reservation_expired",
                        expired_before=now,
                    )
                    if transitioned:
                        reclaimed += 1
                except UsageOperationStateError:
                    pass
        return reclaimed

    def _reclaim_shadow(self, user_id: str, operation_id: str, now: datetime) -> bool:
        """Prepare then settle an expired shadow operation under lease fencing."""
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if (
                operation is None
                or operation.accounting_mode != "shadow"
                or operation.state != "reserved"
                or operation.expires_at > now
            ):
                return False
            execution = (
                self._store.get_item(
                    user_pk(user_id), usage_execution_sk(operation_id), consistent_read=True
                )
                or {}
            )
            execution_expiry = execution.get("expires_at")
            if execution_expiry and _parse_datetime(str(execution_expiry)) > now:
                return False
            if not operation.shadow_pending_outcome:
                if operation.dispatch_evidence_state == "not_dispatched":
                    outcome: ShadowSettlementOutcome = "failed_before_dispatch"
                elif operation.dispatch_evidence_state in ("dispatched", "completed"):
                    outcome = "failed_after_dispatch"
                else:
                    return False
                prepared = operation.with_shadow_pending(
                    **_shadow_pending_values(operation, outcome, None)
                )
                try:
                    self._store.transact_write(
                        [
                            self._operation_put(
                                prepared,
                                expected_state="reserved",
                                expected_expires_at=operation.expires_at,
                                expected_dispatch_evidence_version=operation.dispatch_evidence_version,
                            ),
                            self._event_put(prepared, "shadow_prepare"),
                            self._expired_execution_check(user_id, operation_id, now),
                        ]
                    )
                    continue
                except ClientError as exc:
                    if not _is_transaction_failure(exc):
                        raise
                    continue

            month = self._load_month(operation.user_id, operation.month)
            expected_version = int(month.get("version") or 0)
            usage = operation.shadow_pending_usage or {}
            _apply_amounts(
                month,
                {
                    "articles": int(usage.get("actual_articles") or 0),
                    "tokens": int(usage.get("total_tokens") or 0),
                    "shadow_cost_micro_usd": int(usage.get("actual_cost_micro_usd") or 0),
                },
            )
            month["version"] = expected_version + 1
            settled = operation.settled_shadow()
            try:
                self._store.transact_write(
                    [
                        self._aggregate_put(month, expected_version),
                        self._operation_put(
                            settled,
                            expected_state="reserved",
                            expected_expires_at=operation.expires_at,
                            expected_dispatch_evidence_version=operation.dispatch_evidence_version,
                        ),
                        self._event_put(settled, "shadow_settle"),
                        self._expired_execution_check(user_id, operation_id, now),
                    ]
                )
                return True
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        return False

    def _reclaim_finalize(self, user_id: str, operation_id: str, now: datetime) -> bool:
        """Settle only an operation that remains expired and unowned at commit."""
        for _attempt in range(4):
            operation = self.get_operation(user_id, operation_id)
            if operation is None or operation.state != "reserved" or operation.expires_at > now:
                return False
            execution = (
                self._store.get_item(
                    user_pk(user_id),
                    usage_execution_sk(operation_id),
                    consistent_read=True,
                )
                or {}
            )
            execution_expiry = execution.get("expires_at")
            if execution_expiry and _parse_datetime(str(execution_expiry)) > now:
                return False
            if operation.dispatch_evidence_state in ("dispatched", "completed"):
                request = _finalize_request_from_evidence(operation)
            elif operation.dispatch_evidence_state == "unknown":
                # A legacy private result is positive evidence. Its absence is
                # unresolved, never authorization to release a reservation.
                result = self.get_result(user_id, operation_id)
                if result is None:
                    return False
                try:
                    request = _finalize_request_from_result(operation, result)
                except Exception:
                    request = _conservative_finalize_request(operation)
            else:
                return False

            month = self._load_month(operation.user_id, operation.month)
            expected_version = int(month.get("version") or 0)
            _subtract_reserved(month, operation)
            month["committed_articles"] += operation.reserved_articles
            month["committed_chats"] += operation.reserved_chats
            month["committed_cost_micro_usd"] += request.actual_cost_micro_usd
            month["articles"] += operation.reserved_articles
            month["chats"] += operation.reserved_chats
            month["shadow_cost_micro_usd"] += request.actual_cost_micro_usd
            actual_tokens = request.tokens or request.input_tokens + request.output_tokens
            month["tokens"] += actual_tokens
            month["version"] = expected_version + 1
            finalized = operation.finalized(request, actual_tokens=actual_tokens)
            try:
                self._store.transact_write(
                    [
                        self._aggregate_put(month, expected_version),
                        self._operation_put(
                            finalized,
                            expected_state="reserved",
                            expected_expires_at=operation.expires_at,
                            expected_dispatch_evidence_version=(
                                operation.dispatch_evidence_version
                            ),
                            expected_missing_dispatch_evidence=(
                                operation.dispatch_evidence_state == "unknown"
                                and operation.dispatch_evidence_version == 0
                            ),
                        ),
                        self._event_put(finalized, "finalize"),
                        self._expired_execution_check(user_id, operation_id, now),
                    ]
                )
                return True
            except ClientError as exc:
                if not _is_transaction_failure(exc):
                    raise
        return False

    def _expired_execution_check(
        self, user_id: str, operation_id: str, now: datetime
    ) -> dict[str, Any]:
        return {
            "ConditionCheck": {
                "TableName": self._store.table_name,
                "Key": _serialize({"pk": user_pk(user_id), "sk": usage_execution_sk(operation_id)}),
                "ConditionExpression": "attribute_not_exists(pk) OR #expires_at <= :now",
                "ExpressionAttributeNames": {"#expires_at": "expires_at"},
                "ExpressionAttributeValues": _serialize_values({":now": now.isoformat()}),
            }
        }

    def _load_month(self, user_id: str, month: str) -> dict[str, Any]:
        pk = user_pk(user_id)
        sk = usage_sk(month)
        item = self._store.get_item(pk, sk, consistent_read=True) or {}
        raw_document = item.get(DOCUMENT_ATTRIBUTE)
        document: dict[str, Any] = {}
        if isinstance(raw_document, str):
            parsed = json.loads(raw_document)
            if isinstance(parsed, dict):
                document = parsed
        result = {**empty_usage(user_id, month), **document}
        for field in (*USAGE_FIELDS, *COUNTER_FIELDS, "version"):
            result[field] = int(item.get(field, result.get(field)) or 0)
        _reconcile_compatibility_counters(result)
        return result

    @staticmethod
    def _idempotent_reserve(
        operation: UsageOperation, request: UsageReservationRequest
    ) -> UsageOperation:
        if (
            operation.accounting_mode != request.accounting_mode
            or operation.payload_hash != request.payload_hash
        ):
            raise UsageOperationConflict(
                f"Operation {request.operation_id} has a different payload"
            )
        return operation

    def _aggregate_put(self, month: dict[str, Any], expected_version: int) -> dict[str, Any]:
        document = {key: value for key, value in month.items() if key != "version"}
        item = {
            "pk": user_pk(month["user_id"]),
            "sk": usage_sk(month["month"]),
            DOCUMENT_ATTRIBUTE: _json(document),
            **{field: month[field] for field in (*USAGE_FIELDS, *COUNTER_FIELDS)},
            "version": month["version"],
        }
        put: dict[str, Any] = {
            "TableName": self._store.table_name,
            "Item": _serialize(item),
            "ConditionExpression": (
                "attribute_not_exists(#version)"
                if expected_version == 0
                else "#version = :expected_version"
            ),
            "ExpressionAttributeNames": {"#version": "version"},
        }
        if expected_version:
            put["ExpressionAttributeValues"] = _serialize_values(
                {":expected_version": expected_version}
            )
        return {"Put": put}

    def _operation_put(
        self,
        operation: UsageOperation,
        *,
        create: bool = False,
        expected_state: str | None = None,
        expected_expires_at: datetime | None = None,
        expected_dispatch_evidence_version: int | None = None,
        expected_missing_dispatch_evidence: bool = False,
    ) -> dict[str, Any]:
        record = _operation_to_record(operation)
        item = {
            "pk": user_pk(operation.user_id),
            "sk": usage_operation_sk(operation.operation_id),
            DOCUMENT_ATTRIBUTE: _json(record),
            "state": operation.state,
            "payload_hash": operation.payload_hash,
            "expires_at": operation.expires_at.isoformat(),
            "dispatch_evidence_state": operation.dispatch_evidence_state,
            "dispatch_evidence_version": operation.dispatch_evidence_version,
        }
        put: dict[str, Any] = {
            "TableName": self._store.table_name,
            "Item": _serialize(item),
        }
        if create:
            put["ConditionExpression"] = "attribute_not_exists(pk)"
        elif expected_state is not None:
            conditions = ["#state = :expected_state"]
            names = {"#state": "state"}
            values: dict[str, Any] = {":expected_state": expected_state}
            names["#evidence_version"] = "dispatch_evidence_version"
            if expected_missing_dispatch_evidence:
                conditions.append("attribute_not_exists(#evidence_version)")
            elif expected_dispatch_evidence_version is not None:
                conditions.append("#evidence_version = :expected_evidence_version")
                values[":expected_evidence_version"] = expected_dispatch_evidence_version
            if expected_expires_at is not None:
                conditions.append(
                    "(attribute_not_exists(#expires_at) OR #expires_at = :expected_expires_at)"
                )
                names["#expires_at"] = "expires_at"
                values[":expected_expires_at"] = expected_expires_at.isoformat()
            put["ConditionExpression"] = " AND ".join(conditions)
            put["ExpressionAttributeNames"] = names
            put["ExpressionAttributeValues"] = _serialize_values(values)
        return {"Put": put}

    def _event_put(
        self,
        operation: UsageOperation,
        transition: str,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        record = _event_record(operation, transition, reason=reason)
        return {
            "Put": {
                "TableName": self._store.table_name,
                "Item": _serialize(
                    {
                        "pk": user_pk(operation.user_id),
                        "sk": usage_event_sk(operation.operation_id, transition),
                        DOCUMENT_ATTRIBUTE: _json(record),
                    }
                ),
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        }


def _json(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def _serialize(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: _SERIALIZER.serialize(value) for key, value in item.items()}


def _serialize_values(
    values: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {key: _SERIALIZER.serialize(value) for key, value in values.items()}


def _is_transaction_failure(exc: ClientError) -> bool:
    code = exc.response.get("Error", {}).get("Code")
    if code in {"ConditionalCheckFailedException", "TransactionConflictException"}:
        return True
    if code != "TransactionCanceledException":
        return False

    reasons = exc.response.get("CancellationReasons")
    if not isinstance(reasons, list) or not reasons:
        return False
    reason_codes = {reason.get("Code") for reason in reasons if isinstance(reason, dict)}
    retryable_codes = {"None", "ConditionalCheckFailed", "TransactionConflict"}
    conflict_codes = {"ConditionalCheckFailed", "TransactionConflict"}
    return reason_codes <= retryable_codes and bool(reason_codes & conflict_codes)


class DynamoSubscriptionRepository:
    def __init__(self, store: DynamoDbStore) -> None:
        self._store = store

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self._store.get_document(user_pk(user_id), SK_SUBSCRIPTION, consistent_read=True)

    def upsert(self, user_id: str, record: dict[str, Any]) -> dict[str, Any]:
        for _attempt in range(4):
            current = self.get(user_id)
            stored = self._next_record(user_id, record, current, allow_pending_transition=False)
            if self._write(user_id, stored, current):
                return stored
        raise ValueError("Subscription update conflicted; retry after reconciliation.")

    def compare_and_swap(
        self,
        user_id: str,
        record: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        current = self.get(user_id)
        if self._revision(current) != expected_revision:
            return None
        stored = self._next_record(user_id, record, current, allow_pending_transition=True)
        return stored if self._write(user_id, stored, current) else None

    def find_user_by_customer(self, stripe_customer_id: str) -> str | None:
        if not stripe_customer_id:
            return None
        record = self._store.get_document(
            stripe_customer_pk(stripe_customer_id), SK_SUBSCRIPTION, consistent_read=True
        )
        return record.get("user_id") if record else None

    @staticmethod
    def _revision(record: dict[str, Any] | None) -> int:
        value = (record or {}).get("revision", 0)
        return value if isinstance(value, int) and value >= 0 else 0

    def _next_record(
        self,
        user_id: str,
        record: dict[str, Any],
        current: dict[str, Any] | None,
        *,
        allow_pending_transition: bool,
    ) -> dict[str, Any]:
        stored = dict(record)
        current_pending = (current or {}).get("pending_checkout")
        requested_pending = stored.get("pending_checkout")
        if current_pending and not allow_pending_transition:
            stored["pending_checkout"] = current_pending
        elif current_pending:
            self._validate_pending_transition(current_pending, requested_pending)
        stored["user_id"] = user_id
        stored["revision"] = self._revision(current) + 1
        return stored

    @staticmethod
    def _validate_pending_transition(current: dict[str, Any], requested: object) -> None:
        if not isinstance(requested, dict):
            raise ValueError("A pending checkout operation cannot be removed by a stale writer.")
        immutable = (
            "operation_id",
            "user_id",
            "requested_plan",
            "price_id",
            "success_url",
            "cancel_url",
            "stripe_customer_id",
            "customer_choice",
            "email",
            "idempotency_key",
            "operation_metadata",
            "provider_origin",
        )
        if current.get("state") == "terminal" and current.get("terminal_proof"):
            replacement_operation_id = requested.get("operation_id")
            if (
                requested.get("state") != "reserved"
                or not isinstance(replacement_operation_id, str)
                or replacement_operation_id == current.get("operation_id")
            ):
                raise ValueError(
                    "A terminal checkout can only be replaced by a new reserved operation."
                )
            return
        if any(requested.get(field) != current.get(field) for field in immutable):
            raise ValueError("A pending checkout operation cannot be replaced.")
        for field in (
            "creation_attempted_at",
            "stripe_checkout_session_id",
            "url",
            "expires_at",
            "result_stripe_customer_id",
            "historical_operation_id",
            "historical_checkout_session_id",
        ):
            if current.get(field) is not None and requested.get(field) != current.get(field):
                raise ValueError("Pending checkout evidence cannot be replaced.")
        states = {
            "reserved": 0,
            "attempted": 1,
            "created": 2,
            "adopted": 2,
            "activated": 2,
            "terminal": 3,
        }
        if states.get(str(requested.get("state")), -1) < states.get(str(current.get("state")), -1):
            raise ValueError("Pending checkout state cannot move backwards.")

    def _write(
        self,
        user_id: str,
        stored: dict[str, Any],
        current: dict[str, Any] | None,
    ) -> bool:
        current_customer_id = (current or {}).get("stripe_customer_id")
        customer_id = stored.get("stripe_customer_id")
        if customer_id and not isinstance(customer_id, str):
            raise ValueError("Stripe customer id must be a string.")
        new_index = self._customer_index(customer_id) if customer_id else None
        if new_index:
            owner = new_index.get("user_id")
            if owner != user_id:
                raise ValueError("Stripe customer is already owned by another account.")

        old_index = (
            self._customer_index(current_customer_id)
            if (
                isinstance(current_customer_id, str)
                and current_customer_id
                and current_customer_id != customer_id
            )
            else None
        )
        if old_index and old_index.get("user_id") != user_id:
            raise ValueError("Stripe customer is already owned by another account.")

        transaction = [self._subscription_put(user_id, stored, self._revision(current))]
        if customer_id:
            transaction.append(
                self._customer_index_put(user_id, customer_id, legacy_index=new_index)
            )
        if (
            isinstance(current_customer_id, str)
            and current_customer_id
            and current_customer_id != customer_id
        ):
            transaction.append(
                self._customer_index_delete(user_id, current_customer_id, legacy_index=old_index)
            )
        try:
            self._store.transact_write(transaction)
        except ClientError as exc:
            if _is_transaction_failure(exc):
                return False
            raise
        return True

    def _subscription_put(
        self, user_id: str, document: dict[str, Any], expected_revision: int
    ) -> dict[str, Any]:
        item = {
            "pk": user_pk(user_id),
            "sk": SK_SUBSCRIPTION,
            DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            "revision": document["revision"],
        }
        condition = (
            "attribute_not_exists(#revision)" if expected_revision == 0 else "#revision = :revision"
        )
        values = (
            {}
            if expected_revision == 0
            else {":revision": _SERIALIZER.serialize(expected_revision)}
        )
        return {
            "Put": {
                "TableName": self._store.table_name,
                "Item": {key: _SERIALIZER.serialize(value) for key, value in item.items()},
                "ConditionExpression": condition,
                "ExpressionAttributeNames": {"#revision": "revision"},
                **({"ExpressionAttributeValues": values} if values else {}),
            }
        }

    def _customer_index(self, customer_id: object) -> dict[str, Any] | None:
        if not isinstance(customer_id, str) or not customer_id:
            return None
        return self._store.get_document(
            stripe_customer_pk(customer_id), SK_SUBSCRIPTION, consistent_read=True
        )

    def _customer_index_put(
        self,
        user_id: str,
        customer_id: str,
        *,
        legacy_index: dict[str, Any] | None,
    ) -> dict[str, Any]:
        document = {"user_id": user_id, "stripe_customer_id": customer_id}
        item = {
            "pk": stripe_customer_pk(customer_id),
            "sk": SK_SUBSCRIPTION,
            DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            "owner_user_id": user_id,
        }
        condition = "attribute_not_exists(pk) OR #owner = :owner"
        values = {":owner": _SERIALIZER.serialize(user_id)}
        names = {"#owner": "owner_user_id"}
        if legacy_index is not None:
            condition += " OR #document = :legacy_document"
            names["#document"] = DOCUMENT_ATTRIBUTE
            values[":legacy_document"] = _SERIALIZER.serialize(
                json.dumps(legacy_index, ensure_ascii=False, separators=(",", ":"))
            )
        return {
            "Put": {
                "TableName": self._store.table_name,
                "Item": {key: _SERIALIZER.serialize(value) for key, value in item.items()},
                "ConditionExpression": condition,
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }

    def _customer_index_delete(
        self,
        user_id: str,
        customer_id: str,
        *,
        legacy_index: dict[str, Any] | None,
    ) -> dict[str, Any]:
        condition = "#owner = :owner"
        values = {":owner": _SERIALIZER.serialize(user_id)}
        names = {"#owner": "owner_user_id"}
        if legacy_index is not None:
            condition += " OR #document = :legacy_document"
            names["#document"] = DOCUMENT_ATTRIBUTE
            values[":legacy_document"] = _SERIALIZER.serialize(
                json.dumps(legacy_index, ensure_ascii=False, separators=(",", ":"))
            )
        return {
            "Delete": {
                "TableName": self._store.table_name,
                "Key": {
                    "pk": _SERIALIZER.serialize(stripe_customer_pk(customer_id)),
                    "sk": _SERIALIZER.serialize(SK_SUBSCRIPTION),
                },
                "ConditionExpression": condition,
                "ExpressionAttributeNames": names,
                "ExpressionAttributeValues": values,
            }
        }
