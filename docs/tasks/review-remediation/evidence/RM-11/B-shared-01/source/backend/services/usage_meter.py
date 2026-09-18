"""Atomic plan usage reservation, settlement, and release service."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from accounts import SubscriptionRepository
from core.plans import PlanLimits, get_plan_limits
from core.usage_costs import ModelRate, UnknownModelRateError, load_model_rate
from repositories.usage_repository import (
    ExecutionClaimStatus,
    ShadowSettlementOutcome,
    UsageFinalizeRequest,
    UsageOperation,
    UsageOperationConflict,
    UsageOperationNotFound,
    UsageOperationStateError,
    UsageQuotaExceeded,
    UsageRepository,
    UsageReservationRequest,
)

from services.entitlements import (
    EntitlementError,
    current_month,
    normalize_utc,
    resolve_plan_id,
)

Meter = Literal["article", "chat", "cost"]
logger = logging.getLogger("untangle.usage")


def _log_usage_event(event: str, **fields: Any) -> None:
    """Emit a machine-readable event without request or replay payloads."""
    logger.info(
        json.dumps(
            {"event": event, "metric_name": event, "metric_value": 1, **fields},
            sort_keys=True,
        )
    )


class UsageMeter:
    """Coordinates usage lifecycle operations without a check-then-record gap."""

    def __init__(
        self,
        subscription_repository: SubscriptionRepository,
        usage_repository: UsageRepository,
        user_id: str,
        *,
        rate: ModelRate | None = None,
        now: datetime | None = None,
        plan_loader: Callable[[str | None], PlanLimits] = get_plan_limits,
        reservation_ttl_seconds: int = 900,
        reservation_enabled: bool = True,
        durable_shadow: bool = False,
        provider_mode: str = "stripe",
    ) -> None:
        if durable_shadow and reservation_enabled:
            raise ValueError("durable_shadow requires disabled reservation enforcement")
        self.subscription_repository = subscription_repository
        self.usage_repository = usage_repository
        self.user_id = user_id
        if rate is not None:
            self.rate = rate
            self.pricing_available = bool(
                rate.version
                and rate.input_micro_usd_per_million > 0
                and rate.output_micro_usd_per_million > 0
            )
        elif reservation_enabled:
            self.rate = load_model_rate()
            self.pricing_available = True
        else:
            try:
                self.rate = load_model_rate()
                self.pricing_available = True
            except UnknownModelRateError:
                self.rate = ModelRate(
                    os.getenv("OPENAI_MODEL", "").strip(),
                    0,
                    0,
                    os.getenv("OPENAI_RATE_CARD_VERSION", "").strip(),
                )
                self.pricing_available = False
        self.now = now
        self.plan_loader = plan_loader
        self.reservation_ttl_seconds = reservation_ttl_seconds
        self.reservation_enabled = reservation_enabled
        self.durable_shadow = durable_shadow
        self.provider_mode = provider_mode
        self._disabled_operations: dict[str, UsageOperation] = {}

    def reserve(
        self,
        operation_id: str,
        payload_hash: str,
        meter: Meter,
        estimated_cost_micro_usd: int,
        now: datetime | None = None,
    ) -> UsageOperation:
        if meter not in ("article", "chat", "cost"):
            raise ValueError(f"Unknown usage meter: {meter}")
        moment = normalize_utc(now or self.now or datetime.now(UTC))
        plan = self._current_plan(moment)
        request = UsageReservationRequest(
            operation_id=operation_id,
            user_id=self.user_id,
            month=current_month(moment),
            meter=meter,
            payload_hash=payload_hash,
            plan_id=plan.plan_id,
            rate_card_version=self.rate.version,
            tokenizer_encoding=os.getenv("OPENAI_TOKEN_ENCODING", "o200k_base").strip(),
            expires_at=moment + timedelta(seconds=self.reservation_ttl_seconds),
            articles=1 if meter == "article" else 0,
            chats=1 if meter == "chat" else 0,
            cost_micro_usd=estimated_cost_micro_usd,
            article_limit=plan.articles_per_month,
            chat_limit=plan.chats_per_month,
            cost_micro_usd_limit=plan.cost_micro_usd_per_month,
            sentences_per_article=plan.sentences_per_article,
            source_tokens_per_article=plan.source_tokens_per_article,
            model=self.rate.model,
            input_micro_usd_per_million=self.rate.input_micro_usd_per_million,
            output_micro_usd_per_million=self.rate.output_micro_usd_per_million,
        )
        if self.durable_shadow:
            operation = self.usage_repository.start_shadow(
                replace(
                    request,
                    accounting_mode="shadow",
                    pricing_available=self.pricing_available,
                )
            )
            _log_usage_event(
                "usage_reserved", operation_id=operation_id, meter=meter, enforcement="shadow"
            )
            return operation
        if not self.reservation_enabled:
            operation = self._reserve_disabled(request)
            _log_usage_event(
                "usage_reserved",
                operation_id=operation_id,
                meter=meter,
                plan_id=plan.plan_id,
                estimated_cost_micro_usd=estimated_cost_micro_usd,
                enforcement="shadow",
            )
            return operation

        try:
            reclaimed = self.usage_repository.reclaim_expired(self.user_id, moment)
            if reclaimed:
                _log_usage_event("usage_reclaimed", count=reclaimed)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "usage_reclaim_error",
                        "metric_name": "usage_reclaim_error",
                        "metric_value": 1,
                        "error_type": type(exc).__name__,
                    },
                    sort_keys=True,
                )
            )
        try:
            operation = self.usage_repository.reserve(request)
            _log_usage_event(
                "usage_reserved",
                operation_id=operation_id,
                meter=meter,
                plan_id=plan.plan_id,
                estimated_cost_micro_usd=estimated_cost_micro_usd,
                enforcement="enabled",
            )
            return operation
        except (UsageQuotaExceeded, UsageOperationConflict) as exc:
            _log_usage_event(
                "usage_reserve_blocked",
                operation_id=operation_id,
                meter=meter,
                plan_id=plan.plan_id,
                reason=type(exc).__name__,
            )
            raise _entitlement_error(exc) from exc

    def finalize(
        self,
        operation_id: str,
        usage: Any,
        result_ref: str | None = None,
        *,
        evidence_completeness: Literal["measured", "conservative"] = "measured",
    ) -> UsageOperation:
        values = _usage_values(usage)
        request = UsageFinalizeRequest(
            user_id=self.user_id,
            operation_id=operation_id,
            input_tokens=values["input_tokens"],
            output_tokens=values["output_tokens"],
            tokens=values["total_tokens"],
            actual_cost_micro_usd=values["actual_cost_micro_usd"],
            result_ref=result_ref,
            evidence_completeness=evidence_completeness,
        )
        if self.durable_shadow:
            raise UsageOperationStateError("Durable shadow operations require settle_shadow")
        if not self.reservation_enabled:
            operation = self._disabled_operation(operation_id)
            if operation.state == "finalized":
                return operation
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot finalize {operation.state} operation")
            finalized = operation.finalized(
                request,
                actual_tokens=request.tokens,
            )
            self._disabled_operations[operation_id] = finalized
            _log_usage_event(
                "usage_finalized",
                operation_id=operation_id,
                meter=operation.meter,
                estimated_cost_micro_usd=operation.reserved_cost_micro_usd,
                actual_cost_micro_usd=request.actual_cost_micro_usd,
                enforcement="shadow",
            )
            return finalized
        try:
            operation = self.usage_repository.finalize(request)
            _log_usage_event(
                "usage_finalized",
                operation_id=operation_id,
                meter=operation.meter,
                estimated_cost_micro_usd=operation.reserved_cost_micro_usd,
                actual_cost_micro_usd=operation.actual_cost_micro_usd,
                enforcement="enabled",
            )
            overage = max(
                0,
                operation.actual_cost_micro_usd - operation.reserved_cost_micro_usd,
            )
            if overage:
                _log_usage_event(
                    "usage_overage_observed",
                    operation_id=operation_id,
                    meter=operation.meter,
                    overage_cost_micro_usd=overage,
                    cost_micro_usd_limit=operation.cost_micro_usd_limit,
                    enforcement="enabled",
                )
            return operation
        except UsageQuotaExceeded as exc:
            _log_usage_event(
                "usage_finalize_blocked",
                operation_id=operation_id,
                meter=exc.meter,
                reason=type(exc).__name__,
            )
            raise _entitlement_error(exc) from exc
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "usage_finalization_error",
                        "metric_name": "usage_finalization_error",
                        "metric_value": 1,
                        "operation_id": operation_id,
                        "error_type": type(exc).__name__,
                    },
                    sort_keys=True,
                )
            )
            raise

    def release(self, operation_id: str, reason: str) -> UsageOperation:
        if self.durable_shadow:
            raise UsageOperationStateError("Durable shadow operations require settlement")
        if not self.reservation_enabled:
            operation = self._disabled_operation(operation_id)
            if operation.state == "released":
                return operation
            if operation.state != "reserved":
                raise UsageOperationStateError(f"Cannot release {operation.state} operation")
            released = operation.released(reason)
            self._disabled_operations[operation_id] = released
            _log_usage_event(
                "usage_released",
                operation_id=operation_id,
                meter=operation.meter,
                reason=reason,
                enforcement="shadow",
            )
            return released
        operation = self.usage_repository.release(self.user_id, operation_id, reason=reason)
        _log_usage_event(
            "usage_released",
            operation_id=operation_id,
            meter=operation.meter,
            reason=reason,
            enforcement="enabled",
        )
        return operation

    def _current_plan(self, now: datetime) -> PlanLimits:
        subscription = self.subscription_repository.get(self.user_id)
        return self.plan_loader(
            resolve_plan_id(subscription, now, provider_mode=self.provider_mode)
        )

    def current_plan(self, now: datetime | None = None) -> PlanLimits:
        moment = normalize_utc(now or self.now or datetime.now(UTC))
        return self._current_plan(moment)

    def observe_shadow(
        self,
        operation_id: str,
        meter: Meter,
        estimated_cost_micro_usd: int | None,
        usage: Any,
        *,
        outcome: str,
    ) -> None:
        """Log legacy non-enforcing calibration data without touching usage storage."""
        if self.durable_shadow:
            raise UsageOperationStateError("Durable shadow operations require settlement")
        values = _usage_values(usage)
        fields = {
            "operation_id": operation_id,
            "meter": meter,
            "outcome": outcome,
            "input_tokens": values["input_tokens"],
            "output_tokens": values["output_tokens"],
            "total_tokens": values["total_tokens"],
            "model": self.rate.model,
            "rate_card_version": self.rate.version,
            "tokenizer_encoding": os.getenv("OPENAI_TOKEN_ENCODING", "o200k_base").strip(),
            "enforcement": "shadow",
            "pricing_available": self.pricing_available,
        }
        if self.pricing_available and estimated_cost_micro_usd is not None:
            actual_cost = values["actual_cost_micro_usd"]
            if outcome == "conservative_failure":
                actual_cost = max(actual_cost, estimated_cost_micro_usd)
            fields["estimated_cost_micro_usd"] = estimated_cost_micro_usd
            fields["actual_cost_micro_usd"] = actual_cost
            if actual_cost > 0:
                try:
                    moment = normalize_utc(self.now or datetime.now(UTC))
                    self.usage_repository.add(
                        self.user_id,
                        current_month(moment),
                        shadow_cost_micro_usd=actual_cost,
                    )
                except Exception as exc:
                    logger.error(
                        json.dumps(
                            {
                                "event": "usage_shadow_persistence_error",
                                "metric_name": "usage_shadow_persistence_error",
                                "metric_value": 1,
                                "operation_id": operation_id,
                                "error_type": type(exc).__name__,
                            },
                            sort_keys=True,
                        )
                    )
        _log_usage_event("usage_shadow_observed", **fields)

    def get_operation(self, operation_id: str) -> UsageOperation | None:
        if self.durable_shadow:
            return self.usage_repository.get_operation(self.user_id, operation_id)
        if not self.reservation_enabled:
            return self._disabled_operations.get(operation_id)
        return self.usage_repository.get_operation(self.user_id, operation_id)

    def save_result(self, operation_id: str, result: dict[str, Any]) -> dict[str, Any]:
        if self.durable_shadow:
            return self.usage_repository.save_result(self.user_id, operation_id, result)
        if not self.reservation_enabled:
            return result
        return self.usage_repository.save_result(self.user_id, operation_id, result)

    def dispatch_authorizer(self, operation_id: str, marker: dict[str, Any]) -> Callable[[], None]:
        """Authorize one execution's first provider call after durable persistence."""
        lock = threading.Lock()
        authorized = False

        def authorize() -> None:
            nonlocal authorized
            with lock:
                if authorized:
                    return
                self.save_result(operation_id, marker)
                authorized = True

        return authorize

    def get_result(self, operation_id: str) -> dict[str, Any] | None:
        if self.durable_shadow:
            return self.usage_repository.get_result(self.user_id, operation_id)
        if not self.reservation_enabled:
            return None
        return self.usage_repository.get_result(self.user_id, operation_id)

    def renew(self, operation_id: str, expires_at: datetime) -> UsageOperation:
        if self.durable_shadow:
            return self.usage_repository.renew(
                self.user_id, operation_id, normalize_utc(expires_at)
            )
        if not self.reservation_enabled:
            operation = self._disabled_operation(operation_id)
            renewed = operation.renewed(expires_at)
            self._disabled_operations[operation_id] = renewed
            return renewed
        return self.usage_repository.renew(self.user_id, operation_id, normalize_utc(expires_at))

    def claim_execution(
        self,
        operation_id: str,
        claim_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> ExecutionClaimStatus | None:
        if self.durable_shadow:
            return self.usage_repository.claim_execution(
                self.user_id, operation_id, claim_id, normalize_utc(now), normalize_utc(expires_at)
            )
        if not self.reservation_enabled:
            return "claimed"
        return self.usage_repository.claim_execution(
            self.user_id,
            operation_id,
            claim_id,
            normalize_utc(now),
            normalize_utc(expires_at),
        )

    def release_execution(
        self, operation_id: str, claim_id: str, now: datetime | None = None
    ) -> bool:
        if self.durable_shadow:
            return self.usage_repository.release_execution(
                self.user_id, operation_id, claim_id, normalize_utc(now or datetime.now(UTC))
            )
        if not self.reservation_enabled:
            return True
        return self.usage_repository.release_execution(
            self.user_id,
            operation_id,
            claim_id,
            normalize_utc(now or datetime.now(UTC)),
        )

    def renew_execution(self, operation_id: str, claim_id: str, expires_at: datetime) -> bool:
        if self.durable_shadow:
            return self.usage_repository.renew_execution(
                self.user_id, operation_id, claim_id, normalize_utc(expires_at)
            )
        if not self.reservation_enabled:
            return True
        return self.usage_repository.renew_execution(
            self.user_id,
            operation_id,
            claim_id,
            normalize_utc(expires_at),
        )

    def _reserve_disabled(self, request: UsageReservationRequest) -> UsageOperation:
        existing = self._disabled_operations.get(request.operation_id)
        if existing is not None:
            if existing.payload_hash != request.payload_hash:
                raise _entitlement_error(UsageOperationConflict(request.operation_id))
            return existing
        operation = UsageOperation.reserved(request)
        self._disabled_operations[request.operation_id] = operation
        return operation

    def prepare_shadow_settlement(
        self,
        operation_id: str,
        *,
        outcome: ShadowSettlementOutcome,
        result_ref: str | None = None,
    ) -> UsageOperation:
        if not self.durable_shadow:
            raise UsageOperationStateError("Durable shadow metering is disabled")
        return self.usage_repository.prepare_shadow_settlement(
            self.user_id, operation_id, outcome, result_ref=result_ref
        )

    def settle_shadow(self, operation_id: str) -> UsageOperation:
        if not self.durable_shadow:
            raise UsageOperationStateError("Durable shadow metering is disabled")
        return self.usage_repository.settle_shadow(self.user_id, operation_id)

    def _disabled_operation(self, operation_id: str) -> UsageOperation:
        operation = self._disabled_operations.get(operation_id)
        if operation is None:
            raise UsageOperationNotFound(operation_id)
        return operation


def _usage_values(usage: Any) -> dict[str, int]:
    def value(name: str, fallback: int = 0) -> int:
        if isinstance(usage, dict):
            return int(usage.get(name, fallback) or 0)
        return int(getattr(usage, name, fallback) or 0)

    input_tokens = value("input_tokens")
    output_tokens = value("output_tokens")
    has_actual_cost = (
        "actual_cost_micro_usd" in usage
        if isinstance(usage, dict)
        else hasattr(usage, "actual_cost_micro_usd")
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": value("total_tokens", input_tokens + output_tokens),
        "actual_cost_micro_usd": value("actual_cost_micro_usd")
        if has_actual_cost
        else value("cost_micro_usd"),
    }


def _entitlement_error(
    error: UsageQuotaExceeded | UsageOperationConflict,
) -> EntitlementError:
    if isinstance(error, UsageOperationConflict):
        return EntitlementError(
            "Operation ID was already used for a different payload.",
            code="operation_payload_conflict",
            status_code=409,
        )
    if error.meter == "cost":
        return EntitlementError(
            "Monthly usage limit reached.",
            code="token_budget_exceeded",
            status_code=429,
        )
    return EntitlementError(
        f"Monthly {error.meter} limit reached.",
        code=f"{error.meter}_quota_exceeded",
        status_code=402,
    )
