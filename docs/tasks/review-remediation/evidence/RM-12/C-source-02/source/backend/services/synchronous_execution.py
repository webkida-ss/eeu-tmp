"""Own synchronous replay, execution leases, dispatch evidence, and settlement.

The caller reserves usage and supplies provider work plus response construction.
The context retains the claim through caller-side outcome recording.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from core.ids import generate_uuid7
from core.pipeline import PipelineError, UsageTally
from pydantic import BaseModel
from repositories.usage_repository import UsageOperation

from services.reading_support import (
    _dispatch_was_attempted,
    _log_recovery_event,
    _settlement_usage,
)
from services.usage_meter import UsageMeter

logger = logging.getLogger("untangle.backend")


def _response_from_result_ref(kind: str, result_ref: str | None, model: Any) -> Any | None:
    prefix = f"{kind}:"
    if not result_ref or not result_ref.startswith(prefix):
        return None
    return model(**json.loads(result_ref[len(prefix) :]))


def _recover_synchronous_result(
    meter: UsageMeter,
    operation: Any,
    *,
    kind: str,
    model: Any,
) -> Any | None:
    stored = meter.get_result(operation.operation_id)
    if not stored or stored.get("kind") != kind:
        return None
    if stored.get("state") == "dispatching":
        return None
    response_document = stored.get("response")
    if not isinstance(response_document, dict):
        _settle_durable_dispatch_evidence(meter, operation)
        raise PipelineError(
            "The previous provider dispatch had an uncertain result.",
            status_code=502,
        )
    response = model(**response_document)
    if operation.state == "reserved":
        meter.finalize(
            operation.operation_id,
            operation.dispatch_usage or stored["usage"],
            result_ref=f"usage-result:{operation.operation_id}",
            evidence_completeness=(
                "measured"
                if operation.dispatch_evidence_state == "unknown"
                or operation.dispatch_usage_completeness == "measured"
                else "conservative"
            ),
        )
        _log_recovery_event(
            "pending_result_repaired",
            operation_id=operation.operation_id,
            kind=kind,
        )
    return response


def _finalize_synchronous_evidence(
    meter: UsageMeter,
    operation: Any,
    *,
    fallback_usage: dict[str, Any] | None = None,
    result_ref: str | None = None,
) -> None:
    """Finalize the canonical evidence, retaining local usage after a failed promotion."""
    latest = meter.get_operation(operation.operation_id) or operation
    if latest.state == "finalized":
        return
    if latest.dispatch_evidence_state == "completed":
        usage = latest.dispatch_usage or {
            "actual_cost_micro_usd": latest.reserved_cost_micro_usd
        }
        completeness = (
            "measured"
            if latest.dispatch_usage_completeness == "measured"
            else "conservative"
        )
    elif fallback_usage is not None:
        usage = fallback_usage
        completeness = "measured" if usage.get("usage_complete") is True else "conservative"
    elif latest.dispatch_evidence_state == "dispatched":
        usage = {"actual_cost_micro_usd": latest.reserved_cost_micro_usd}
        completeness = "conservative"
    else:
        return
    meter.finalize(
        latest.operation_id,
        usage,
        result_ref=result_ref or f"usage-evidence:{latest.operation_id}",
        evidence_completeness=completeness,
    )


def _settle_durable_dispatch_evidence(meter: UsageMeter, operation: Any) -> None:
    if operation.dispatch_evidence_state not in ("dispatched", "completed"):
        return
    _finalize_synchronous_evidence(meter, operation)
    raise PipelineError(
        "The previous provider dispatch had an uncertain result.",
        status_code=502,
    )


def _claim_or_await_synchronous_execution(
    meter: UsageMeter,
    operation: Any,
    *,
    kind: str,
    model: Any,
) -> tuple[str | None, Any | None, float]:
    claim_id = generate_uuid7()
    wait_seconds = max(0.0, float(os.getenv("SYNC_EXECUTION_WAIT_SECONDS", "2")))
    lease_seconds = max(1.0, float(os.getenv("SYNC_EXECUTION_LEASE_SECONDS", "120")))
    deadline = time.monotonic() + wait_seconds
    claim_contended = False
    while True:
        latest = meter.get_operation(operation.operation_id)
        if latest is not None:
            recovered = _recover_synchronous_result(meter, latest, kind=kind, model=model)
            if recovered:
                return None, recovered, lease_seconds
            if latest.state == "finalized":
                raise PipelineError(
                    "The previous provider attempt had an uncertain result.",
                    status_code=502,
                )
            if latest.state == "released":
                raise PipelineError(
                    "This operation is no longer executable. Start a new operation.",
                    status_code=409,
                )
        now = datetime.now(UTC)
        claim_status = meter.claim_execution(
            operation.operation_id,
            claim_id,
            now,
            now + timedelta(seconds=lease_seconds),
        )
        if claim_status:
            if claim_contended or claim_status == "recovered":
                _log_recovery_event(
                    "execution_lease_recovered",
                    operation_id=operation.operation_id,
                    kind=kind,
                )
            pending = meter.get_result(operation.operation_id)
            latest = meter.get_operation(operation.operation_id)
            if latest is not None:
                try:
                    _settle_durable_dispatch_evidence(meter, latest)
                except PipelineError:
                    meter.release_execution(operation.operation_id, claim_id, now)
                    raise
            if pending and pending.get("state") == "dispatching":
                meter.finalize(
                    operation.operation_id,
                    pending["usage"],
                    result_ref=f"usage-result:{operation.operation_id}",
                    evidence_completeness="conservative",
                )
                _log_recovery_event(
                    "pending_result_repaired",
                    operation_id=operation.operation_id,
                    kind=kind,
                    outcome="uncertain_dispatch",
                )
                meter.release_execution(operation.operation_id, claim_id, now)
                raise PipelineError(
                    "The previous provider dispatch had an uncertain result.",
                    status_code=502,
                )
            return claim_id, None, lease_seconds
        claim_contended = True
        if time.monotonic() >= deadline:
            raise PipelineError(
                "This operation is already in progress. Please retry shortly.",
                status_code=409,
            )
        time.sleep(0.02)


class _SynchronousExecutionHeartbeat:
    def __init__(
        self,
        meter: UsageMeter,
        operation_id: str,
        claim_id: str,
        lease_seconds: float,
    ) -> None:
        self.meter = meter
        self.operation_id = operation_id
        self.claim_id = claim_id
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"sync-operation-heartbeat-{operation_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        interval = max(0.1, self.lease_seconds / 3)
        while not self._stop.wait(interval):
            if not self._renew_once():
                self._lost.set()
                return

    def _renew_once(self) -> bool:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        try:
            if not self.meter.renew_execution(self.operation_id, self.claim_id, expires_at):
                return False
        except Exception:
            logger.exception(
                "synchronous execution claim heartbeat failed operation_id=%s",
                self.operation_id,
            )
            return False
        try:
            self.meter.renew(self.operation_id, expires_at)
        except Exception:
            logger.warning(
                "usage reservation heartbeat failed while execution claim remains owned operation_id=%s",
                self.operation_id,
            )
        return True

    def stop_and_verify(self) -> bool:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.lease_seconds))
        if self._thread.is_alive() or self._lost.is_set():
            return False
        return self._renew_once()


def _settle_synchronous_failure(
    meter: UsageMeter,
    operation: Any,
    error: Exception,
    *,
    tally: UsageTally,
    kind: str,
    dispatch_attempted: bool,
) -> None:
    if dispatch_attempted:
        usage = _settlement_usage(tally, operation)
        try:
            meter.save_result(
                operation.operation_id,
                {
                    "kind": kind,
                    "state": "completed",
                    "usage": usage,
                },
            )
        except Exception:  # noqa: BLE001 - preserve the prior durable marker for settlement
            logger.warning(
                "synchronous partial evidence could not be saved operation_id=%s",
                operation.operation_id,
            )
        latest = meter.get_operation(operation.operation_id)
        if latest and latest.dispatch_evidence_state in ("dispatched", "completed"):
            _finalize_synchronous_evidence(
                meter,
                latest,
                fallback_usage=usage,
                result_ref=f"usage-evidence:{operation.operation_id}",
            )
            return
        pending = meter.get_result(operation.operation_id)
        if pending and pending.get("state") == "completed":
            return
        if pending and pending.get("state") == "dispatching":
            meter.finalize(
                operation.operation_id,
                pending["usage"],
                result_ref=f"usage-result:{operation.operation_id}",
                evidence_completeness="conservative",
            )
            return
        meter.finalize(
            operation.operation_id,
            {"actual_cost_micro_usd": operation.reserved_cost_micro_usd},
            evidence_completeness="conservative",
        )
    else:
        meter.release(operation.operation_id, "failed_before_dispatch")


def _configure_synchronous_dispatch_marker(
    tally: UsageTally | None,
    meter: UsageMeter,
    operation: Any,
    kind: str,
) -> None:
    if tally is None:
        return
    marker = {
        "kind": kind,
        "state": "dispatching",
        "usage": {"actual_cost_micro_usd": operation.reserved_cost_micro_usd},
    }
    tally.set_dispatch_callback(meter.dispatch_authorizer(operation.operation_id, marker))


class SynchronousExecution[ResponseT: BaseModel]:
    """Hold one execution claim until replay or settlement and caller work finish."""

    def __init__(
        self,
        meter: UsageMeter,
        operation: UsageOperation,
        *,
        kind: str,
        response_model: type[ResponseT],
    ) -> None:
        self.meter = meter
        self.operation = operation
        self.kind = kind
        self.response_model = response_model
        self.replay: ResponseT | None = None
        self.usage: dict[str, Any] | None = None
        self._claim_id: str | None = None
        self._lease_seconds = 0.0
        self._started = False

    def __enter__(self) -> SynchronousExecution[ResponseT]:
        self.replay = _recover_synchronous_result(
            self.meter,
            self.operation,
            kind=self.kind,
            model=self.response_model,
        )
        if self.replay is not None:
            return self
        if self.operation.state == "finalized":
            self.replay = _response_from_result_ref(
                self.kind,
                self.operation.result_ref,
                self.response_model,
            )
            if self.replay is not None:
                return self
            raise PipelineError(
                "The previous provider attempt had an uncertain result.",
                status_code=502,
            )
        self._claim_id, self.replay, self._lease_seconds = _claim_or_await_synchronous_execution(
            self.meter,
            self.operation,
            kind=self.kind,
            model=self.response_model,
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._claim_id:
            try:
                self.meter.release_execution(self.operation.operation_id, self._claim_id)
            finally:
                self._claim_id = None

    def run[ProviderT](
        self,
        tally: UsageTally,
        dispatch: Callable[[], ProviderT],
        build_response: Callable[[ProviderT], ResponseT],
        *,
        on_failure: Callable[[Exception], None] | None = None,
    ) -> ResponseT:
        """Dispatch once, verify ownership, persist the result, then settle usage."""
        if self.replay is not None:
            return self.replay
        if self._claim_id is None:
            raise RuntimeError("Synchronous execution requires an acquired claim.")
        if self._started:
            raise RuntimeError("Synchronous execution can dispatch only once per claim.")
        self._started = True
        _configure_synchronous_dispatch_marker(tally, self.meter, self.operation, self.kind)
        heartbeat = _SynchronousExecutionHeartbeat(
            self.meter,
            self.operation.operation_id,
            self._claim_id,
            self._lease_seconds,
        )
        provider_error = None
        heartbeat.start()
        try:
            provider_result = dispatch()
        except Exception as error:
            provider_error = error
        finally:
            owns_execution = heartbeat.stop_and_verify()
        if not owns_execution:
            error = PipelineError(
                "Execution ownership was lost before settlement.",
                status_code=409,
            )
            if on_failure:
                on_failure(error)
            raise error
        if provider_error is not None:
            if on_failure:
                on_failure(provider_error)
            _settle_synchronous_failure(
                self.meter,
                self.operation,
                provider_error,
                tally=tally,
                kind=self.kind,
                dispatch_attempted=_dispatch_was_attempted(tally, provider_error),
            )
            raise provider_error
        try:
            response = build_response(provider_result)
            self.usage = _settlement_usage(tally, self.operation)
            self.meter.save_result(
                self.operation.operation_id,
                {
                    "kind": self.kind,
                    "state": "completed",
                    "response": response.model_dump(),
                    "usage": self.usage,
                },
            )
            latest_operation = (
                self.meter.get_operation(self.operation.operation_id) or self.operation
            )
            _finalize_synchronous_evidence(
                self.meter,
                latest_operation,
                fallback_usage=self.usage,
                result_ref=f"usage-result:{self.operation.operation_id}",
            )
        except Exception as error:
            if on_failure:
                on_failure(error)
            _settle_synchronous_failure(
                self.meter,
                self.operation,
                error,
                tally=tally,
                kind=self.kind,
                dispatch_attempted=True,
            )
            raise
        return response
