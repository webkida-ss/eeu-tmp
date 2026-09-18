from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from storage.json_list_store import json_list_lock, read_json_list, write_json_list

USAGE_FIELDS = ("articles", "chats", "tokens", "shadow_cost_micro_usd")
COUNTER_FIELDS = (
    "committed_articles",
    "reserved_articles",
    "committed_chats",
    "reserved_chats",
    "committed_cost_micro_usd",
    "reserved_cost_micro_usd",
)
COMPATIBILITY_COUNTER_PAIRS = (
    ("articles", "committed_articles"),
    ("chats", "committed_chats"),
    ("shadow_cost_micro_usd", "committed_cost_micro_usd"),
)
OperationState = Literal["reserved", "finalized", "released"]
ExecutionClaimStatus = Literal["claimed", "owned", "recovered"]
DispatchEvidenceState = Literal["unknown", "not_dispatched", "dispatched", "completed", "settled"]
UsageCompleteness = Literal["unknown", "measured", "conservative"]
AccountingMode = Literal["enforced", "shadow"]
ShadowSettlementOutcome = Literal["success", "failed_before_dispatch", "failed_after_dispatch"]


class UsageRepositoryError(RuntimeError):
    """Base class for stable usage persistence failures."""


class UsageQuotaExceeded(UsageRepositoryError):
    def __init__(self, meter: str) -> None:
        self.meter = meter
        super().__init__(f"{meter}_quota_exceeded")


class UsageOperationConflict(UsageRepositoryError):
    pass


class UsageOperationNotFound(UsageRepositoryError):
    pass


class UsageOperationStateError(UsageRepositoryError):
    pass


class UsageResultTooLarge(UsageRepositoryError):
    pass


def _nonnegative(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class UsageReservationRequest:
    operation_id: str
    user_id: str
    month: str
    meter: str
    payload_hash: str
    plan_id: str
    rate_card_version: str
    expires_at: datetime
    tokenizer_encoding: str = ""
    articles: int = 0
    chats: int = 0
    cost_micro_usd: int = 0
    article_limit: int = 0
    chat_limit: int = 0
    cost_micro_usd_limit: int = 0
    sentences_per_article: int = 0
    source_tokens_per_article: int = 0
    model: str = ""
    input_micro_usd_per_million: int = 0
    output_micro_usd_per_million: int = 0
    accounting_mode: AccountingMode = "enforced"
    pricing_available: bool | None = None

    def __post_init__(self) -> None:
        for field in (
            "articles",
            "chats",
            "cost_micro_usd",
            "article_limit",
            "chat_limit",
            "cost_micro_usd_limit",
            "sentences_per_article",
            "source_tokens_per_article",
            "input_micro_usd_per_million",
            "output_micro_usd_per_million",
        ):
            _nonnegative(field, getattr(self, field))
        if not isinstance(self.expires_at, datetime):
            raise ValueError("expires_at must be a datetime")
        if self.accounting_mode not in ("enforced", "shadow"):
            raise ValueError("accounting_mode is invalid")


@dataclass(frozen=True)
class UsageFinalizeRequest:
    user_id: str
    operation_id: str
    actual_cost_micro_usd: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens: int = 0
    result_ref: str | None = None
    evidence_completeness: UsageCompleteness = "measured"

    def __post_init__(self) -> None:
        for field in ("actual_cost_micro_usd", "input_tokens", "output_tokens", "tokens"):
            _nonnegative(field, getattr(self, field))
        if self.evidence_completeness not in ("measured", "conservative"):
            raise ValueError("evidence_completeness is invalid")


@dataclass(frozen=True)
class UsageOperation:
    operation_id: str
    user_id: str
    month: str
    meter: str
    payload_hash: str
    plan_id: str
    rate_card_version: str
    article_limit: int
    chat_limit: int
    cost_micro_usd_limit: int
    sentences_per_article: int
    source_tokens_per_article: int
    model: str
    input_micro_usd_per_million: int
    output_micro_usd_per_million: int
    reserved_articles: int
    reserved_chats: int
    reserved_cost_micro_usd: int
    state: OperationState
    expires_at: datetime
    tokenizer_encoding: str = ""
    result_ref: str | None = None
    actual_articles: int = 0
    actual_chats: int = 0
    actual_cost_micro_usd: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens: int = 0
    release_reason: str | None = None
    dispatch_evidence_state: DispatchEvidenceState = "unknown"
    dispatch_evidence_version: int = 0
    dispatch_kind: str | None = None
    dispatch_usage_completeness: UsageCompleteness = "unknown"
    dispatch_usage: dict[str, int] | None = None
    accounting_mode: AccountingMode = "enforced"
    pricing_available: bool | None = None
    shadow_pending_outcome: ShadowSettlementOutcome | None = None
    shadow_pending_usage: dict[str, int] | None = None
    shadow_pending_completeness: UsageCompleteness = "unknown"
    shadow_pending_result_ref: str | None = None
    shadow_outcome: ShadowSettlementOutcome | None = None

    @classmethod
    def reserved(cls, request: UsageReservationRequest) -> UsageOperation:
        return cls(
            operation_id=request.operation_id,
            user_id=request.user_id,
            month=request.month,
            meter=request.meter,
            payload_hash=request.payload_hash,
            plan_id=request.plan_id,
            rate_card_version=request.rate_card_version,
            tokenizer_encoding=request.tokenizer_encoding,
            article_limit=request.article_limit,
            chat_limit=request.chat_limit,
            cost_micro_usd_limit=request.cost_micro_usd_limit,
            sentences_per_article=request.sentences_per_article,
            source_tokens_per_article=request.source_tokens_per_article,
            model=request.model,
            input_micro_usd_per_million=request.input_micro_usd_per_million,
            output_micro_usd_per_million=request.output_micro_usd_per_million,
            reserved_articles=request.articles,
            reserved_chats=request.chats,
            reserved_cost_micro_usd=request.cost_micro_usd,
            state="reserved",
            expires_at=request.expires_at,
            dispatch_evidence_state="not_dispatched",
            dispatch_evidence_version=1,
            accounting_mode=request.accounting_mode,
            pricing_available=request.pricing_available,
        )

    def finalized(
        self,
        request: UsageFinalizeRequest,
        *,
        actual_tokens: int,
    ) -> UsageOperation:
        return replace(
            self,
            state="finalized",
            result_ref=request.result_ref,
            actual_articles=self.reserved_articles,
            actual_chats=self.reserved_chats,
            actual_cost_micro_usd=request.actual_cost_micro_usd,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            tokens=actual_tokens,
            dispatch_evidence_state="settled",
            dispatch_evidence_version=self.dispatch_evidence_version + 1,
            dispatch_usage_completeness=request.evidence_completeness,
            dispatch_usage=(
                _usage_record_from_finalize(request, actual_tokens)
                if request.evidence_completeness == "measured"
                else _preserve_conservative_usage(self.dispatch_usage, request, actual_tokens)
            ),
        )

    def released(self, reason: str) -> UsageOperation:
        return replace(
            self,
            state="released",
            release_reason=reason,
            dispatch_evidence_version=self.dispatch_evidence_version + 1,
        )

    def renewed(self, expires_at: datetime) -> UsageOperation:
        return replace(
            self,
            expires_at=expires_at,
            dispatch_evidence_version=self.dispatch_evidence_version + 1,
        )

    def with_dispatch_evidence(
        self,
        *,
        state: DispatchEvidenceState,
        kind: str | None,
        completeness: UsageCompleteness,
        usage: dict[str, int] | None,
    ) -> UsageOperation:
        if self.state != "reserved":
            raise UsageOperationStateError(
                f"Cannot record dispatch evidence for {self.state} operation"
            )
        if self.dispatch_evidence_state == "settled":
            raise UsageOperationStateError("Cannot replace settled dispatch evidence")
        return replace(
            self,
            dispatch_evidence_state=state,
            dispatch_evidence_version=self.dispatch_evidence_version + 1,
            dispatch_kind=kind or self.dispatch_kind,
            dispatch_usage_completeness=completeness,
            dispatch_usage=usage if usage is not None else self.dispatch_usage,
        )

    def with_shadow_pending(
        self,
        *,
        outcome: ShadowSettlementOutcome,
        usage: dict[str, int],
        completeness: UsageCompleteness,
        result_ref: str | None,
    ) -> UsageOperation:
        if self.accounting_mode != "shadow" or self.state != "reserved":
            raise UsageOperationStateError("Cannot prepare settlement for this operation")
        if self.shadow_pending_outcome:
            if (
                self.shadow_pending_outcome != outcome
                or self.shadow_pending_usage != usage
                or self.shadow_pending_completeness != completeness
                or self.shadow_pending_result_ref != result_ref
            ):
                raise UsageOperationConflict("Shadow settlement outcome conflicts")
            return self
        return replace(
            self,
            shadow_pending_outcome=outcome,
            shadow_pending_usage=usage,
            shadow_pending_completeness=completeness,
            shadow_pending_result_ref=result_ref,
            dispatch_evidence_version=self.dispatch_evidence_version + 1,
        )

    def settled_shadow(self) -> UsageOperation:
        if self.accounting_mode != "shadow" or not self.shadow_pending_outcome:
            raise UsageOperationStateError("Shadow settlement is not prepared")
        usage = self.shadow_pending_usage or {}
        return replace(
            self,
            state="finalized",
            result_ref=self.shadow_pending_result_ref,
            actual_articles=int(usage.get("actual_articles") or 0),
            actual_cost_micro_usd=int(usage.get("actual_cost_micro_usd") or 0),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            tokens=int(usage.get("total_tokens") or 0),
            dispatch_evidence_state="settled",
            dispatch_evidence_version=self.dispatch_evidence_version + 1,
            dispatch_usage_completeness=self.shadow_pending_completeness,
            dispatch_usage={key: value for key, value in usage.items() if key != "actual_articles"},
            shadow_outcome=self.shadow_pending_outcome,
        )

    @property
    def articles(self) -> int:
        return self.reserved_articles

    @property
    def chats(self) -> int:
        return self.reserved_chats

    @property
    def cost_micro_usd(self) -> int:
        return self.reserved_cost_micro_usd


def empty_usage(user_id: str, month: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "month": month,
        "articles": 0,
        "chats": 0,
        "tokens": 0,
        "shadow_cost_micro_usd": 0,
        "committed_articles": 0,
        "reserved_articles": 0,
        "committed_chats": 0,
        "reserved_chats": 0,
        "committed_cost_micro_usd": 0,
        "reserved_cost_micro_usd": 0,
        "plan_id": None,
        "article_limit": 0,
        "chat_limit": 0,
        "cost_micro_usd_limit": 0,
        "sentences_per_article": 0,
        "source_tokens_per_article": 0,
    }


class UsageRepository(Protocol):
    """Idempotent monthly usage reservation lifecycle."""

    def get_month(self, user_id: str, month: str) -> dict[str, Any]: ...

    def reserve(self, request: UsageReservationRequest) -> UsageOperation: ...

    def start_shadow(self, request: UsageReservationRequest) -> UsageOperation: ...

    def prepare_shadow_settlement(
        self,
        user_id: str,
        operation_id: str,
        outcome: ShadowSettlementOutcome,
        *,
        result_ref: str | None = None,
    ) -> UsageOperation: ...

    def settle_shadow(self, user_id: str, operation_id: str) -> UsageOperation: ...

    def finalize(self, request: UsageFinalizeRequest) -> UsageOperation: ...

    def release(self, user_id: str, operation_id: str, *, reason: str) -> UsageOperation: ...

    def get_operation(self, user_id: str, operation_id: str) -> UsageOperation | None: ...

    def save_result(
        self, user_id: str, operation_id: str, result: dict[str, Any]
    ) -> dict[str, Any]: ...

    def get_result(self, user_id: str, operation_id: str) -> dict[str, Any] | None: ...

    def renew(self, user_id: str, operation_id: str, expires_at: datetime) -> UsageOperation: ...

    def claim_execution(
        self,
        user_id: str,
        operation_id: str,
        claim_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionClaimStatus | None: ...

    def release_execution(
        self, user_id: str, operation_id: str, claim_id: str, now: datetime
    ) -> bool: ...

    def renew_execution(
        self,
        user_id: str,
        operation_id: str,
        claim_id: str,
        expires_at: datetime,
    ) -> bool: ...

    def reclaim_expired(self, user_id: str, now: datetime) -> int: ...

    def add(self, user_id: str, month: str, **amounts: int) -> dict[str, Any]: ...


def _apply_amounts(record: dict[str, Any], amounts: dict[str, int]) -> dict[str, Any]:
    _validate_add_amounts(amounts)
    for field, amount in amounts.items():
        record[field] = int(record.get(field) or 0) + amount
        if record.get("plan_id"):
            committed_field = next(
                (committed for raw, committed in COMPATIBILITY_COUNTER_PAIRS if raw == field),
                None,
            )
            if committed_field:
                record[committed_field] = int(record.get(committed_field) or 0) + amount
    return record


def _validate_add_amounts(amounts: dict[str, int]) -> None:
    for field, amount in amounts.items():
        if field not in USAGE_FIELDS:
            raise ValueError(f"Unknown usage field: {field}")
        if type(amount) is not int or amount < 0:
            raise ValueError(f"{field} must be a non-negative integer")


class JsonUsageRepository:
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, path: Path) -> None:
        self._path = path
        lock_key = str(path.resolve())
        with self._locks_guard:
            self._lock = self._locks.setdefault(lock_key, threading.RLock())

    def _load_items_with_cleanup(self) -> list[dict[str, Any]]:
        items = read_json_list(self._path)
        removed = _sweep_expired_results(items, datetime.now(UTC))
        if removed:
            write_json_list(self._path, items)
        return items

    def get_month(self, user_id: str, month: str) -> dict[str, Any]:
        with self._lock, json_list_lock(self._path):
            for item in self._load_items_with_cleanup():
                if _is_month(item, user_id, month):
                    return _normalized_month(item, user_id, month)
            return empty_usage(user_id, month)

    def add(self, user_id: str, month: str, **amounts: int) -> dict[str, Any]:
        _validate_add_amounts(amounts)
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            for item in items:
                if _is_month(item, user_id, month):
                    _apply_amounts(item, amounts)
                    write_json_list(self._path, items)
                    return _normalized_month(item, user_id, month)

            record = _apply_amounts(empty_usage(user_id, month), amounts)
            record["record_type"] = "usage_month"
            items.append(record)
            write_json_list(self._path, items)
            return _normalized_month(record, user_id, month)

    def reserve(self, request: UsageReservationRequest) -> UsageOperation:
        if request.accounting_mode != "enforced":
            raise UsageOperationStateError("Shadow operations require start_shadow")
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            existing = _find_operation(items, request.user_id, request.operation_id)
            if existing is not None:
                operation = _operation_from_record(existing)
                if (
                    operation.accounting_mode != "enforced"
                    or operation.payload_hash != request.payload_hash
                ):
                    raise UsageOperationConflict(
                        f"Operation {request.operation_id} has a different payload"
                    )
                return operation

            month = _get_or_add_month(items, request.user_id, request.month)
            _ratchet_limits(month, request)
            _check_admission(month, request)

            month["reserved_articles"] += request.articles
            month["reserved_chats"] += request.chats
            month["reserved_cost_micro_usd"] += request.cost_micro_usd
            operation = UsageOperation.reserved(request)
            items.append(_operation_to_record(operation))
            items.append(_event_record(operation, "reserve"))
            write_json_list(self._path, items)
            return operation

    def start_shadow(self, request: UsageReservationRequest) -> UsageOperation:
        if request.accounting_mode != "shadow":
            raise UsageOperationStateError("Shadow operation mode is required")
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            existing = _find_operation(items, request.user_id, request.operation_id)
            if existing is not None:
                operation = _operation_from_record(existing)
                if (
                    operation.accounting_mode != "shadow"
                    or operation.payload_hash != request.payload_hash
                ):
                    raise UsageOperationConflict("Shadow operation identity conflicts")
                return operation
            operation = UsageOperation.reserved(request)
            items.append(_operation_to_record(operation))
            items.append(_event_record(operation, "shadow_start"))
            write_json_list(self._path, items)
            return operation

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
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            record = _find_operation(items, user_id, operation_id)
            if record is None:
                raise UsageOperationNotFound(operation_id)
            operation = _operation_from_record(record)
            if operation.accounting_mode != "shadow":
                raise UsageOperationStateError("Operation is not shadow accounted")
            if operation.state == "finalized":
                if operation.shadow_outcome != outcome or operation.result_ref != result_ref:
                    raise UsageOperationConflict("Shadow settlement outcome conflicts")
                return operation
            pending = _shadow_pending_values(operation, outcome, result_ref)
            prepared = operation.with_shadow_pending(**pending)
            if prepared != operation:
                record.clear()
                record.update(_operation_to_record(prepared))
                items.append(_event_record(prepared, "shadow_prepare"))
                write_json_list(self._path, items)
            return prepared

    def settle_shadow(self, user_id: str, operation_id: str) -> UsageOperation:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            record = _find_operation(items, user_id, operation_id)
            if record is None:
                raise UsageOperationNotFound(operation_id)
            operation = _operation_from_record(record)
            if operation.accounting_mode != "shadow":
                raise UsageOperationStateError("Operation is not shadow accounted")
            if operation.state == "finalized":
                return operation
            settled = _settle_shadow_operation_in_items(items, record, operation)
            write_json_list(self._path, items)
            return settled

    def finalize(self, request: UsageFinalizeRequest) -> UsageOperation:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            record = _find_operation(items, request.user_id, request.operation_id)
            if record is None:
                raise UsageOperationNotFound(request.operation_id)
            operation = _operation_from_record(record)
            if operation.accounting_mode != "enforced":
                raise UsageOperationStateError("Shadow operations require settle_shadow")
            if operation.state == "finalized":
                return operation
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot finalize {operation.state} operation")

            if operation.dispatch_evidence_state == "completed":
                request = _finalize_request_from_evidence(operation)

            finalized = _finalize_operation_in_items(items, record, operation, request)
            write_json_list(self._path, items)
            return finalized

    def release(self, user_id: str, operation_id: str, *, reason: str) -> UsageOperation:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            record = _find_operation(items, user_id, operation_id)
            if record is None:
                raise UsageOperationNotFound(operation_id)
            operation = _operation_from_record(record)
            if operation.accounting_mode != "enforced":
                raise UsageOperationStateError("Shadow operations cannot be released")
            if operation.state == "released":
                return operation
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot release {operation.state} operation")
            if operation.dispatch_evidence_state != "not_dispatched":
                raise UsageOperationStateError("Cannot release an operation with dispatch evidence")

            month = _find_month(items, operation.user_id, operation.month)
            if month is None:
                raise UsageRepositoryError("Usage aggregate is missing")
            month = _normalize_month_in_place(month, operation.user_id, operation.month)
            _subtract_reserved(month, operation)
            released = operation.released(reason)
            record.clear()
            record.update(_operation_to_record(released))
            items.append(_event_record(released, "release", reason=reason))
            write_json_list(self._path, items)
            return released

    def get_operation(self, user_id: str, operation_id: str) -> UsageOperation | None:
        with self._lock, json_list_lock(self._path):
            record = _find_operation(self._load_items_with_cleanup(), user_id, operation_id)
            return _operation_from_record(record) if record is not None else None

    def save_result(
        self, user_id: str, operation_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        expires_at = datetime.now(UTC) + timedelta(
            seconds=max(1, int(os.getenv("SYNC_RESULT_TTL_SECONDS", "86400")))
        )
        stored = {
            "record_type": "usage_result",
            "user_id": user_id,
            "operation_id": operation_id,
            "expires_at": expires_at.isoformat(),
            **result,
        }
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            operation_record = _find_operation(items, user_id, operation_id)
            if operation_record is not None:
                operation = _operation_from_record(operation_record)
                promoted = _promote_dispatch_evidence(operation, result)
                if promoted != operation:
                    operation_record.clear()
                    operation_record.update(_operation_to_record(promoted))
                    # Keep accounting evidence even when a TTL-private response
                    # later proves too large or cannot be written.
                    write_json_list(self._path, items)

            _validate_result_size(stored)
            existing = _find_result(items, user_id, operation_id)
            if existing is not None:
                comparable = {
                    key: value
                    for key, value in existing.items()
                    if key
                    not in {
                        "record_type",
                        "user_id",
                        "operation_id",
                        "expires_at",
                    }
                }
                if comparable.get("state") == "dispatching" and result.get("state") == "completed":
                    items[items.index(existing)] = stored
                    write_json_list(self._path, items)
                    return result
                if comparable != result:
                    raise UsageOperationConflict(
                        f"Operation {operation_id} has a different stored result"
                    )
                return comparable
            items.append(stored)
            write_json_list(self._path, items)
            return result

    def get_result(self, user_id: str, operation_id: str) -> dict[str, Any] | None:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            record = _find_result(items, user_id, operation_id)
            if record is None:
                return None
            expires_at = record.get("expires_at")
            if expires_at and _parse_datetime(expires_at) <= datetime.now(UTC):
                items.remove(record)
                write_json_list(self._path, items)
                return None
            return {
                key: value
                for key, value in record.items()
                if key
                not in {
                    "record_type",
                    "user_id",
                    "operation_id",
                    "expires_at",
                }
            }

    def renew(self, user_id: str, operation_id: str, expires_at: datetime) -> UsageOperation:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            record = _find_operation(items, user_id, operation_id)
            if record is None:
                raise UsageOperationNotFound(operation_id)
            operation = _operation_from_record(record)
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot renew {operation.state} operation")
            renewed = operation.renewed(expires_at)
            record.clear()
            record.update(_operation_to_record(renewed))
            write_json_list(self._path, items)
            return renewed

    def claim_execution(
        self,
        user_id: str,
        operation_id: str,
        claim_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionClaimStatus | None:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            existing = _find_execution(items, user_id, operation_id)
            if existing is not None and _parse_datetime(existing["expires_at"]) > now:
                return "owned" if existing.get("claim_id") == claim_id else None
            recovered = existing is not None
            claimed = {
                "record_type": "usage_execution",
                "user_id": user_id,
                "operation_id": operation_id,
                "claim_id": claim_id,
                "expires_at": expires_at.isoformat(),
            }
            if existing is None:
                items.append(claimed)
            else:
                existing.clear()
                existing.update(claimed)
            write_json_list(self._path, items)
            return "recovered" if recovered else "claimed"

    def release_execution(
        self, user_id: str, operation_id: str, claim_id: str, now: datetime
    ) -> bool:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            existing = _find_execution(items, user_id, operation_id)
            if existing is None or existing.get("claim_id") != claim_id:
                return False
            existing["expires_at"] = now.isoformat()
            write_json_list(self._path, items)
            return True

    def renew_execution(
        self,
        user_id: str,
        operation_id: str,
        claim_id: str,
        expires_at: datetime,
    ) -> bool:
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            existing = _find_execution(items, user_id, operation_id)
            if existing is None or existing.get("claim_id") != claim_id:
                return False
            existing["expires_at"] = expires_at.isoformat()
            write_json_list(self._path, items)
            return True

    def reclaim_expired(self, user_id: str, now: datetime) -> int:
        reclaimed = 0
        with self._lock, json_list_lock(self._path):
            items = self._load_items_with_cleanup()
            for record in items:
                if not (
                    record.get("record_type") == "usage_operation"
                    and record.get("user_id") == user_id
                    and record.get("state") == "reserved"
                ):
                    continue
                try:
                    expired = _parse_datetime(record["expires_at"]) <= now
                except Exception:
                    continue
                if not expired:
                    continue
                execution = _find_execution(items, user_id, str(record["operation_id"]))
                if execution and _parse_datetime(execution["expires_at"]) > now:
                    continue
                try:
                    operation = _operation_from_record(record)
                except Exception:
                    continue
                if operation.accounting_mode == "shadow":
                    try:
                        outcome: ShadowSettlementOutcome
                        if operation.shadow_pending_outcome:
                            _settle_shadow_operation_in_items(items, record, operation)
                            reclaimed += 1
                            continue
                        if operation.dispatch_evidence_state == "not_dispatched":
                            outcome = "failed_before_dispatch"
                        elif operation.dispatch_evidence_state in ("dispatched", "completed"):
                            outcome = "failed_after_dispatch"
                        else:
                            continue
                        prepared = operation.with_shadow_pending(
                            **_shadow_pending_values(operation, outcome, None)
                        )
                        record.clear()
                        record.update(_operation_to_record(prepared))
                        _settle_shadow_operation_in_items(items, record, prepared)
                        reclaimed += 1
                    except Exception:
                        continue
                    continue
                if operation.dispatch_evidence_state in ("dispatched", "completed"):
                    try:
                        _finalize_operation_in_items(
                            items,
                            record,
                            operation,
                            _finalize_request_from_evidence(operation),
                        )
                    except Exception:
                        continue
                    reclaimed += 1
                    continue
                result = _find_result(items, user_id, operation.operation_id)
                if operation.dispatch_evidence_state == "unknown":
                    # Old operations have no durable marker. A surviving private
                    # result is positive historical evidence; its absence is not.
                    if result is None:
                        continue
                    try:
                        request = _finalize_request_from_result(operation, result)
                    except Exception:
                        request = _conservative_finalize_request(operation)
                    try:
                        _finalize_operation_in_items(items, record, operation, request)
                    except Exception:
                        continue
                    reclaimed += 1
                    continue
                if operation.dispatch_evidence_state != "not_dispatched":
                    continue
                month = _find_month(items, operation.user_id, operation.month)
                if month is None:
                    raise UsageRepositoryError("Usage aggregate is missing")
                month = _normalize_month_in_place(month, operation.user_id, operation.month)
                _subtract_reserved(month, operation)
                released = operation.released("reservation_expired")
                record.clear()
                record.update(_operation_to_record(released))
                items.append(
                    _event_record(
                        released,
                        "release",
                        reason="reservation_expired",
                    )
                )
                reclaimed += 1
            if reclaimed:
                write_json_list(self._path, items)
        return reclaimed


def _is_month(item: dict[str, Any], user_id: str, month: str) -> bool:
    return (
        item.get("record_type") in (None, "usage_month")
        and item.get("user_id") == user_id
        and item.get("month") == month
        and "operation_id" not in item
    )


def _normalized_month(item: dict[str, Any], user_id: str, month: str) -> dict[str, Any]:
    result = {**empty_usage(user_id, month), **item}
    for field in (*USAGE_FIELDS, *COUNTER_FIELDS):
        result[field] = int(result.get(field) or 0)
    _reconcile_compatibility_counters(result)
    return result


def _normalize_month_in_place(item: dict[str, Any], user_id: str, month: str) -> dict[str, Any]:
    normalized = _normalized_month(item, user_id, month)
    item.clear()
    item.update(normalized)
    item["record_type"] = "usage_month"
    return item


def _find_month(items: list[dict[str, Any]], user_id: str, month: str) -> dict[str, Any] | None:
    return next((item for item in items if _is_month(item, user_id, month)), None)


def _get_or_add_month(items: list[dict[str, Any]], user_id: str, month: str) -> dict[str, Any]:
    existing = _find_month(items, user_id, month)
    if existing is not None:
        return _normalize_month_in_place(existing, user_id, month)
    record = {**empty_usage(user_id, month), "record_type": "usage_month"}
    items.append(record)
    return record


def _find_operation(
    items: list[dict[str, Any]], user_id: str, operation_id: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in items
            if item.get("record_type") == "usage_operation"
            and item.get("user_id") == user_id
            and item.get("operation_id") == operation_id
        ),
        None,
    )


def _find_result(
    items: list[dict[str, Any]], user_id: str, operation_id: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in items
            if item.get("record_type") == "usage_result"
            and item.get("user_id") == user_id
            and item.get("operation_id") == operation_id
        ),
        None,
    )


def _find_execution(
    items: list[dict[str, Any]], user_id: str, operation_id: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in items
            if item.get("record_type") == "usage_execution"
            and item.get("user_id") == user_id
            and item.get("operation_id") == operation_id
        ),
        None,
    )


def _validate_result_size(record: dict[str, Any]) -> None:
    ceiling = min(
        350000,
        max(1, int(os.getenv("SYNC_RESULT_MAX_BYTES", "65536"))),
    )
    size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > ceiling:
        raise UsageResultTooLarge(
            f"Usage result exceeds serialized size ceiling ({size}>{ceiling})"
        )


def _usage_record_from_finalize(
    request: UsageFinalizeRequest, actual_tokens: int
) -> dict[str, int]:
    return {
        "actual_cost_micro_usd": request.actual_cost_micro_usd,
        "input_tokens": request.input_tokens,
        "output_tokens": request.output_tokens,
        "total_tokens": actual_tokens,
    }


def _preserve_conservative_usage(
    existing: dict[str, int] | None,
    request: UsageFinalizeRequest,
    actual_tokens: int,
) -> dict[str, int] | None:
    existing = existing or {}
    return {
        "actual_cost_micro_usd": max(
            int(existing.get("actual_cost_micro_usd") or 0),
            request.actual_cost_micro_usd,
        ),
        "input_tokens": max(int(existing.get("input_tokens") or 0), request.input_tokens),
        "output_tokens": max(int(existing.get("output_tokens") or 0), request.output_tokens),
        "total_tokens": max(int(existing.get("total_tokens") or 0), actual_tokens),
    }


def _normalized_result_usage(
    result: dict[str, Any],
) -> tuple[UsageCompleteness, dict[str, int] | None]:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return "unknown", None
    values: dict[str, int] = {}
    present = False
    malformed = False
    aliases = {
        "actual_cost_micro_usd": ("actual_cost_micro_usd", "cost_micro_usd"),
        "input_tokens": ("input_tokens",),
        "output_tokens": ("output_tokens",),
        "total_tokens": ("total_tokens",),
    }
    for target, names in aliases.items():
        matching = next((name for name in names if name in usage), None)
        if matching is None:
            values[target] = 0
            continue
        present = True
        raw = usage[matching]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            # A malformed counter cannot erase independently valid lower
            # bounds, which remain useful for conservative settlement.
            malformed = True
            continue
        values[target] = raw
    if not present:
        return "unknown", None
    if "total_tokens" not in values and ("input_tokens" in values or "output_tokens" in values):
        values["total_tokens"] = values.get("input_tokens", 0) + values.get("output_tokens", 0)
    for target in aliases:
        values.setdefault(target, 0)
    # A response object alone is not usage evidence. New callers supply this
    # flag from UsageTally; numeric-only historical results remain compatible.
    complete = usage.get("usage_complete")
    if complete is None:
        complete = not bool(usage.get("missing_usage", False))
    if malformed or complete is not True:
        return "unknown", values
    return "measured", values


def _promote_dispatch_evidence(operation: UsageOperation, result: dict[str, Any]) -> UsageOperation:
    state = str(result.get("state") or "completed")
    kind = result.get("kind")
    if kind is not None and kind not in {"analyze", "chat", "preload"}:
        raise UsageOperationConflict("Dispatch evidence kind is invalid")
    if operation.dispatch_kind and kind and operation.dispatch_kind != kind:
        raise UsageOperationConflict("Dispatch evidence kind conflicts with the operation")
    if operation.accounting_mode == "shadow" and operation.shadow_pending_outcome:
        raise UsageOperationConflict("Prepared shadow settlement cannot accept later evidence")
    if state == "dispatching":
        if operation.dispatch_evidence_state != "not_dispatched":
            raise UsageOperationStateError("Dispatch is already authorized or unavailable")
        return operation.with_dispatch_evidence(
            state="dispatched",
            kind=kind,
            completeness="unknown",
            usage=None,
        )
    if state != "completed":
        raise UsageOperationConflict("Dispatch evidence state is invalid")
    completeness, usage = _normalized_result_usage(result)
    if operation.dispatch_evidence_state == "settled":
        raise UsageOperationStateError("Cannot replace settled dispatch evidence")
    if operation.dispatch_evidence_state == "completed":
        existing_usage = operation.dispatch_usage or {}
        if operation.dispatch_usage_completeness == "measured":
            if completeness == "measured" and usage != existing_usage:
                raise UsageOperationConflict("Completed dispatch evidence conflicts")
            if usage and any(
                value > int(existing_usage.get(key) or 0) for key, value in usage.items()
            ):
                raise UsageOperationConflict("Completed dispatch evidence conflicts")
            return operation
        merged_usage = {
            key: max(int(existing_usage.get(key) or 0), int((usage or {}).get(key) or 0))
            for key in {
                "actual_cost_micro_usd",
                "input_tokens",
                "output_tokens",
                "total_tokens",
            }
            if key in existing_usage or key in (usage or {})
        }
        can_promote_measured = completeness == "measured" and all(
            int((usage or {}).get(key) or 0) >= int(existing_usage.get(key) or 0)
            for key in existing_usage
        )
        return operation.with_dispatch_evidence(
            state="completed",
            kind=kind,
            completeness="measured" if can_promote_measured else "unknown",
            usage=usage if can_promote_measured else merged_usage or None,
        )
    return operation.with_dispatch_evidence(
        state="completed",
        kind=kind,
        completeness=completeness,
        usage=usage,
    )


def _conservative_finalize_request(operation: UsageOperation) -> UsageFinalizeRequest:
    usage = operation.dispatch_usage or {}
    known_cost = int(usage.get("actual_cost_micro_usd") or 0)
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    tokens = max(int(usage.get("total_tokens") or 0), input_tokens + output_tokens)
    return UsageFinalizeRequest(
        user_id=operation.user_id,
        operation_id=operation.operation_id,
        actual_cost_micro_usd=max(operation.reserved_cost_micro_usd, known_cost),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens=tokens,
        result_ref=f"usage-evidence:{operation.operation_id}",
        evidence_completeness="conservative",
    )


def _finalize_request_from_evidence(operation: UsageOperation) -> UsageFinalizeRequest:
    if operation.dispatch_usage_completeness != "measured":
        return _conservative_finalize_request(operation)
    usage = operation.dispatch_usage or {}
    return UsageFinalizeRequest(
        user_id=operation.user_id,
        operation_id=operation.operation_id,
        actual_cost_micro_usd=int(usage["actual_cost_micro_usd"]),
        input_tokens=int(usage["input_tokens"]),
        output_tokens=int(usage["output_tokens"]),
        tokens=int(usage["total_tokens"]),
        result_ref=f"usage-evidence:{operation.operation_id}",
        evidence_completeness="measured",
    )


def _shadow_pending_values(
    operation: UsageOperation,
    outcome: ShadowSettlementOutcome,
    result_ref: str | None,
) -> dict[str, Any]:
    if outcome not in ("success", "failed_before_dispatch", "failed_after_dispatch"):
        raise UsageOperationConflict("Shadow settlement outcome is invalid")
    if operation.accounting_mode != "shadow":
        raise UsageOperationStateError("Operation is not shadow accounted")
    if outcome == "failed_before_dispatch":
        if operation.dispatch_evidence_state != "not_dispatched":
            raise UsageOperationConflict("Dispatch evidence conflicts with shadow outcome")
        return {
            "outcome": outcome,
            "usage": {
                "actual_articles": 0,
                "actual_cost_micro_usd": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
            "completeness": "unknown",
            "result_ref": result_ref,
        }
    if outcome == "success" and operation.dispatch_evidence_state != "completed":
        raise UsageOperationConflict("Successful shadow settlement requires completed evidence")
    if outcome == "failed_after_dispatch" and operation.dispatch_evidence_state not in (
        "dispatched",
        "completed",
    ):
        raise UsageOperationConflict("Failed shadow settlement requires dispatch evidence")
    request = _finalize_request_from_evidence(operation)
    completeness: UsageCompleteness = request.evidence_completeness
    if operation.pricing_available is not True:
        request = _conservative_finalize_request(operation)
        completeness = "conservative"
    return {
        "outcome": outcome,
        "usage": {
            "actual_articles": 1 if outcome == "success" else 0,
            "actual_cost_micro_usd": request.actual_cost_micro_usd,
            "input_tokens": request.input_tokens,
            "output_tokens": request.output_tokens,
            "total_tokens": request.tokens,
        },
        "completeness": completeness,
        "result_ref": result_ref,
    }


def _settle_shadow_operation_in_items(
    items: list[dict[str, Any]], record: dict[str, Any], operation: UsageOperation
) -> UsageOperation:
    if operation.accounting_mode != "shadow" or not operation.shadow_pending_outcome:
        raise UsageOperationStateError("Shadow settlement is not prepared")
    month = _get_or_add_month(items, operation.user_id, operation.month)
    usage = operation.shadow_pending_usage or {}
    _apply_amounts(
        month,
        {
            "articles": int(usage.get("actual_articles") or 0),
            "tokens": int(usage.get("total_tokens") or 0),
            "shadow_cost_micro_usd": int(usage.get("actual_cost_micro_usd") or 0),
        },
    )
    settled = operation.settled_shadow()
    record.clear()
    record.update(_operation_to_record(settled))
    items.append(_event_record(settled, "shadow_settle"))
    return settled


def _sweep_expired_results(items: list[dict[str, Any]], now: datetime) -> int:
    limit = min(
        1000,
        max(
            1,
            int(os.getenv("SYNC_RESULT_CLEANUP_BATCH_SIZE", "100")),
        ),
    )
    expired = [
        item
        for item in items
        if item.get("record_type") == "usage_result"
        and item.get("expires_at")
        and _parse_datetime(str(item["expires_at"])) <= now
    ][:limit]
    for item in expired:
        items.remove(item)
    return len(expired)


def _finalize_request_from_result(
    operation: UsageOperation, result: dict[str, Any]
) -> UsageFinalizeRequest:
    usage = result.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cost_value = usage.get("cost_micro_usd")
    if cost_value is None:
        cost_value = usage.get("actual_cost_micro_usd")
    return UsageFinalizeRequest(
        user_id=operation.user_id,
        operation_id=operation.operation_id,
        actual_cost_micro_usd=int(0 if cost_value is None else cost_value),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
        result_ref=f"usage-result:{operation.operation_id}",
    )


def _finalize_operation_in_items(
    items: list[dict[str, Any]],
    record: dict[str, Any],
    operation: UsageOperation,
    request: UsageFinalizeRequest,
) -> UsageOperation:
    month = _find_month(items, operation.user_id, operation.month)
    if month is None:
        raise UsageRepositoryError("Usage aggregate is missing")
    month = _normalize_month_in_place(month, operation.user_id, operation.month)
    _subtract_reserved(month, operation)
    month["committed_articles"] += operation.reserved_articles
    month["committed_chats"] += operation.reserved_chats
    month["committed_cost_micro_usd"] += request.actual_cost_micro_usd
    month["articles"] += operation.reserved_articles
    month["chats"] += operation.reserved_chats
    month["shadow_cost_micro_usd"] += request.actual_cost_micro_usd
    actual_tokens = request.tokens or request.input_tokens + request.output_tokens
    month["tokens"] = int(month.get("tokens") or 0) + actual_tokens
    finalized = operation.finalized(request, actual_tokens=actual_tokens)
    record.clear()
    record.update(_operation_to_record(finalized))
    items.append(_event_record(finalized, "finalize"))
    return finalized


def _ratchet_limits(month: dict[str, Any], request: UsageReservationRequest) -> None:
    _reconcile_compatibility_counters(month, force=True)
    old_limits = (
        month["article_limit"],
        month["chat_limit"],
        month["cost_micro_usd_limit"],
        month["sentences_per_article"],
        month["source_tokens_per_article"],
    )
    new_limits = (
        max(old_limits[0], request.article_limit),
        max(old_limits[1], request.chat_limit),
        max(old_limits[2], request.cost_micro_usd_limit),
        max(old_limits[3], request.sentences_per_article),
        max(old_limits[4], request.source_tokens_per_article),
    )
    (
        month["article_limit"],
        month["chat_limit"],
        month["cost_micro_usd_limit"],
        month["sentences_per_article"],
        month["source_tokens_per_article"],
    ) = new_limits
    if month.get("plan_id") is None or new_limits != old_limits:
        month["plan_id"] = request.plan_id


def _reconcile_compatibility_counters(month: dict[str, Any], *, force: bool = False) -> None:
    """Keep shadow/rollback totals aligned with reservation admission totals."""
    if not force and not month.get("plan_id"):
        return
    for raw_field, committed_field in COMPATIBILITY_COUNTER_PAIRS:
        total = max(
            int(month.get(raw_field) or 0),
            int(month.get(committed_field) or 0),
        )
        month[raw_field] = total
        month[committed_field] = total


def _check_admission(month: dict[str, Any], request: UsageReservationRequest) -> None:
    checks = (
        (
            "article",
            month["committed_articles"],
            month["reserved_articles"],
            request.articles,
            month["article_limit"],
        ),
        (
            "chat",
            month["committed_chats"],
            month["reserved_chats"],
            request.chats,
            month["chat_limit"],
        ),
        (
            "cost",
            month["committed_cost_micro_usd"],
            month["reserved_cost_micro_usd"],
            request.cost_micro_usd,
            month["cost_micro_usd_limit"],
        ),
    )
    for meter, committed, reserved, requested, limit in checks:
        if requested and committed + reserved + requested > limit:
            raise UsageQuotaExceeded(meter)


def _subtract_reserved(month: dict[str, Any], operation: UsageOperation) -> None:
    deductions = {
        "reserved_articles": operation.reserved_articles,
        "reserved_chats": operation.reserved_chats,
        "reserved_cost_micro_usd": operation.reserved_cost_micro_usd,
    }
    for field, amount in deductions.items():
        month[field] = max(0, int(month.get(field) or 0) - amount)


def _operation_to_record(operation: UsageOperation) -> dict[str, Any]:
    record = asdict(operation)
    record["record_type"] = "usage_operation"
    record["expires_at"] = operation.expires_at.isoformat()
    return record


def _operation_from_record(record: dict[str, Any]) -> UsageOperation:
    compatibility_defaults = {
        "sentences_per_article": 0,
        "source_tokens_per_article": 0,
        "tokenizer_encoding": "",
        "dispatch_evidence_state": "unknown",
        "dispatch_evidence_version": 0,
        "dispatch_kind": None,
        "dispatch_usage_completeness": "unknown",
        "dispatch_usage": None,
    }
    values = {
        field.name: record.get(field.name, compatibility_defaults.get(field.name, field.default))
        for field in UsageOperation.__dataclass_fields__.values()
    }
    values["expires_at"] = _parse_datetime(record["expires_at"])
    return UsageOperation(**values)


def _event_record(
    operation: UsageOperation, transition: str, *, reason: str | None = None
) -> dict[str, Any]:
    event = {
        "record_type": "usage_event",
        "event_id": f"{operation.operation_id}:{transition}",
        "operation_id": operation.operation_id,
        "user_id": operation.user_id,
        "month": operation.month,
        "transition": transition,
        "reason": reason,
        "rate_card_version": operation.rate_card_version,
        "tokenizer_encoding": operation.tokenizer_encoding,
        "model": operation.model,
        "input_tokens": operation.input_tokens,
        "output_tokens": operation.output_tokens,
        "tokens": operation.tokens,
        "actual_cost_micro_usd": operation.actual_cost_micro_usd,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if transition == "finalize":
        event["overage_cost_micro_usd"] = max(
            0,
            operation.actual_cost_micro_usd - operation.reserved_cost_micro_usd,
        )
    return event


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)
