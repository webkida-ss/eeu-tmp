"""Preload submission and deferred worker execution.

Owns enqueue recovery, processing leases, and publication of settled results.
Read-only projections and synchronous calls live in separate modules.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from accounts import SubscriptionRepository
from core.ids import generate_uuid7
from core.pipeline import (
    UsageTally,
    _analyze_sentences,
    _estimate_sentence_count,
    _extract_article_text,
    _extract_study_items,
    _prepare_article_content,
    _resolve_language_pair,
    _resolve_vocabulary_coverage_percent,
    _split_sentences,
    estimate_article_cost_micro_usd,
)
from core.usage_costs import ModelRate
from jobs.runner import PreloadJobRunner
from repositories.admin_activity import AdminActivityRepository
from repositories.page_preload_repository import (
    PagePreloadRepository,
    PreloadResultTooLarge,
    normalize_page_url,
)
from repositories.usage_repository import UsageOperationStateError, UsageRepository
from schemas import (
    PagePreloadRequest,
    PagePreloadStatusResponse,
)
from storage.preload_content_store import PreloadContentStore

from services.admin_activity import TerminalActivityOutcome, record_terminal_activity
from services.entitlements import EntitlementError, EntitlementGuard, build_guard
from services.reading_queries import (
    record_status as _record_status,
)
from services.reading_queries import (
    to_status_response as _to_status_response,
)
from services.reading_support import (
    _dispatch_was_attempted,
    _log_recovery_event,
    _settlement_usage,
    _shadow_estimate,
    _shadow_usage,
    canonical_payload_hash,
)
from services.usage_meter import UsageMeter

logger = logging.getLogger("untangle.backend")


def _has_expired_preload_lease(record: dict[str, Any], now: datetime) -> bool:
    if record.get("status") != "running":
        return False
    try:
        expires_at = datetime.fromisoformat(str(record.get("lease_expires_at") or ""))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        return False
    return expires_at.astimezone(UTC) <= now.astimezone(UTC)


# A "processing" record older than this is treated as stale (its worker
# almost certainly died); a resubmit is allowed to replace it. A fresher
# one short-circuits so a double-click does not enqueue the job twice.
STALE_PROCESSING_AFTER_SECONDS = 15 * 60


def _configure_preload_dispatch_marker(
    meter: UsageMeter,
    operation: Any,
    tally: UsageTally,
) -> None:
    """Persist incurred-cost evidence immediately before first dispatch."""
    marker = {
        "kind": "preload",
        "state": "dispatching",
        "usage": {"actual_cost_micro_usd": (operation.reserved_cost_micro_usd)},
    }
    tally.set_dispatch_callback(lambda: meter.save_result(operation.operation_id, marker))


def _require_published_transition(
    repository: PagePreloadRepository,
    user_id: str,
    preload_id: str,
    completed: bool,
) -> None:
    if not completed and repository.get_by_id(user_id, preload_id):
        raise RuntimeError(f"Preload {preload_id} settlement was not published; retry required.")


def _normalize_learner_level(learner_level: str | None) -> str | None:
    normalized = " ".join(str(learner_level or "").split())
    return normalized or None


def _learner_profile_fingerprint(
    learner_level: str | None,
    vocabulary_coverage_percent: float,
) -> str:
    payload = json.dumps(
        {
            "learner_level": _normalize_learner_level(learner_level),
            "vocabulary_coverage_percent": vocabulary_coverage_percent,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_fresh_processing(record: dict[str, Any], now: datetime | None = None) -> bool:
    if _record_status(record) not in ("processing", "running"):
        return False
    requested_at = record.get("requested_at")
    if not requested_at:
        return False
    try:
        requested = datetime.fromisoformat(requested_at)
    except (TypeError, ValueError):
        return False
    moment = now or datetime.now(UTC)
    return (moment - requested).total_seconds() < STALE_PROCESSING_AFTER_SECONDS


def _recover_failed_content_handoff(
    repository: PagePreloadRepository,
    content_store: PreloadContentStore,
    user_id: str,
    record: dict[str, Any],
    usage_meter: UsageMeter | None,
) -> dict[str, Any]:
    """Complete a persisted handoff failure without granting a stale owner control."""
    if record.get("status") != "failed_pending_release":
        return record
    operation_id = str(record.get("operation_id") or "")
    has_reserved_operation = bool(record.get("reservation_enabled"))
    if (
        usage_meter
        and operation_id
        and "reservation_enabled" not in record
        and usage_meter.get_operation(operation_id) is not None
    ):
        has_reserved_operation = True
    if usage_meter and operation_id and has_reserved_operation:
        usage_meter.release(operation_id, str(record.get("failure_reason") or "handoff_failed"))
    content_store.retire(user_id, str(record["id"]))
    recovered = {
        **record,
        "status": "failed",
        "usage_state": (
            "released"
            if usage_meter and operation_id and has_reserved_operation
            else record.get("usage_state")
        ),
        "content_retirement_pending": False,
    }
    repository.finish_processing(
        user_id,
        str(record["id"]),
        str(record.get("learner_profile_fingerprint") or ""),
        recovered,
        expected_status="failed_pending_release",
    )
    return repository.get_by_id(user_id, str(record["id"])) or recovered


def _retire_terminal_content(
    repository: PagePreloadRepository,
    content_store: PreloadContentStore,
    user_id: str,
    record: dict[str, Any],
    learner_profile_fingerprint: str,
) -> dict[str, Any]:
    """Retire a terminal worker payload and retain a retry marker on failure."""
    if not record.get("content_retirement_pending"):
        return record
    if record.get("learner_profile_fingerprint") != learner_profile_fingerprint:
        return record
    try:
        content_store.retire(user_id, str(record["id"]))
    except Exception:  # noqa: BLE001 - retry is driven by an authenticated worker replay
        logger.warning(
            "preload content retirement pending user=%s preload_id=%s",
            user_id,
            record["id"],
        )
        return record
    retired = {**record, "content_retirement_pending": False}
    repository.finish_processing(
        user_id,
        str(record["id"]),
        learner_profile_fingerprint,
        retired,
        expected_status=str(record.get("status") or ""),
    )
    return repository.get_by_id(user_id, str(record["id"])) or retired


def submit_preload(
    repository: PagePreloadRepository,
    job_runner: PreloadJobRunner,
    content_store: PreloadContentStore,
    user_id: str,
    request: PagePreloadRequest,
    guard: EntitlementGuard | None = None,
    usage_meter: UsageMeter | None = None,
    admin_activity_repository: AdminActivityRepository | None = None,
) -> PagePreloadStatusResponse:
    """Fast, synchronous submit: extract the article text (no OpenAI), save a
    "processing" record, and hand the slow analysis off to the job runner.

    The response returns immediately (HTTP 202 semantics) so the call never
    hits API Gateway's 30-second integration cap; the client polls
    ``get_preload_status`` until the record is ready or failed.
    """
    # A fresh "processing" record short-circuits: a double submit (e.g. two
    # tabs, a double-click) must not enqueue the job twice. check_article only
    # reads, but skipping it here also avoids a redundant quota read.
    vocabulary_coverage_percent = _resolve_vocabulary_coverage_percent(
        request.vocabulary_coverage_percent
    )
    learner_level = _normalize_learner_level(request.learner_level)
    learner_profile_fingerprint = _learner_profile_fingerprint(
        learner_level, vocabulary_coverage_percent
    )
    reservation_enabled = bool(usage_meter and usage_meter.reservation_enabled)
    shadow_enabled = bool(usage_meter and not reservation_enabled)
    existing = repository.get_by_page_url(user_id, request.page_url)
    if existing and _is_fresh_processing(existing) and not reservation_enabled:
        existing_fingerprint = existing.get(
            "learner_profile_fingerprint"
        ) or _learner_profile_fingerprint(
            existing.get("learner_level"),
            _resolve_vocabulary_coverage_percent(existing.get("vocabulary_coverage_percent")),
        )
        if existing_fingerprint == learner_profile_fingerprint:
            return _to_status_response(existing)

    if guard and not reservation_enabled:
        try:
            guard.check_article()
        except EntitlementError as exc:
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome(
                    operation_id=request.operation_id,
                    user_id=user_id,
                    operation="article",
                    status="quota_blocked",
                    error=exc,
                    model=usage_meter.rate.model if usage_meter else None,
                ),
                preserve_failure=True,
            )
            raise

    # Extraction is fast and OpenAI-free; a PipelineError (e.g. unextractable
    # HTML, 400) still surfaces synchronously to the caller.
    content = _extract_article_text(
        html=request.html,
        page_url=request.page_url,
        page_title=request.page_title,
    )
    target, native = _resolve_language_pair(request.target_language, request.native_language)
    plan = usage_meter.current_plan() if usage_meter else (guard.plan if guard else None)
    sentence_limit = plan.sentences_per_article if plan else None
    source_token_limit = plan.source_tokens_per_article if plan else None
    prepared = _prepare_article_content(
        content,
        sentence_limit=sentence_limit,
        source_token_limit=source_token_limit,
    )

    payload_hash = canonical_payload_hash(request, exclude={"operation_id"})
    requested_record = repository.get_by_id(user_id, request.operation_id)
    existing_matches_request = bool(
        existing
        and existing.get("payload_hash") == payload_hash
        and (existing.get("learner_profile_fingerprint") == learner_profile_fingerprint)
    )
    if (
        reservation_enabled
        and requested_record is None
        and existing_matches_request
        and _is_fresh_processing(existing)
        and existing.get("operation_id") != request.operation_id
    ):
        return _to_status_response(existing)
    operation = None
    estimated_cost = 0
    if reservation_enabled or shadow_enabled:

        def estimate() -> int:
            return estimate_article_cost_micro_usd(
                prepared,
                page_title=request.page_title,
                vocabulary_coverage_percent=vocabulary_coverage_percent,
                target=target,
                native=native,
                learner_level=learner_level,
            )

        estimated_cost = estimate() if reservation_enabled else _shadow_estimate(estimate)
    if reservation_enabled:
        try:
            operation = usage_meter.reserve(
                request.operation_id,
                payload_hash,
                "article",
                estimated_cost,
            )
        except EntitlementError as exc:
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome(
                    operation_id=request.operation_id,
                    user_id=user_id,
                    operation="article",
                    status="quota_blocked",
                    error=exc,
                    model=usage_meter.rate.model,
                ),
                preserve_failure=True,
            )
            raise
        operation_record = repository.get_by_id(user_id, operation.operation_id)
        if operation_record and operation_record.get("status") == "failed_pending_release":
            recovered = _recover_failed_content_handoff(
                repository,
                content_store,
                user_id,
                operation_record,
                usage_meter,
            )
            return _to_status_response(recovered)
        if (
            existing
            and existing.get("operation_id") == operation.operation_id
            and existing.get("payload_hash") == operation.payload_hash
        ):
            if (
                existing.get("enqueue_state") in ("pending", "queued_unconfirmed")
                and existing.get("status") == "processing"
                and not existing.get("lease_id")
            ):
                if existing.get("enqueue_state") == "pending":
                    if not repository.mark_enqueue_submitting(user_id, existing["id"]):
                        current = repository.get_by_id(user_id, existing["id"])
                        return _to_status_response(current or existing)
                    existing = repository.get_by_id(user_id, existing["id"]) or existing
                usage_context = {
                    key: existing[key]
                    for key in (
                        "operation_id",
                        "payload_hash",
                        "usage_month",
                        "quota_plan",
                        "article_limit",
                        "chat_limit",
                        "cost_micro_usd_limit",
                        "sentence_limit",
                        "source_token_limit",
                        "source_tokens_detected",
                        "source_tokens_analyzed",
                        "rate_card_version",
                        "model",
                        "input_micro_usd_per_million",
                        "output_micro_usd_per_million",
                        "estimated_cost_micro_usd",
                    )
                    if key in existing
                }
                job_runner.enqueue(
                    user_id,
                    existing["page_url"],
                    existing["id"],
                    existing["learner_profile_fingerprint"],
                    usage_context,
                )
                try:
                    confirmed = repository.confirm_enqueued(user_id, existing["id"])
                except Exception:
                    logger.exception(
                        "replay enqueue confirmation failed after submission user=%s preload_id=%s",
                        user_id,
                        existing["id"],
                    )
                    current = repository.get_by_id(user_id, existing["id"])
                    return _to_status_response(current or existing)
                current = repository.get_by_id(user_id, existing["id"])
                if not confirmed:
                    logger.warning(
                        "replay enqueue confirmation lost race user=%s preload_id=%s",
                        user_id,
                        existing["id"],
                    )
                return _to_status_response(current or existing)
            return _to_status_response(existing)
        if operation.state == "finalized":
            replay = repository.get_by_id(user_id, operation.result_ref or request.operation_id)
            if replay:
                return _to_status_response(replay)

    now = datetime.now(UTC).isoformat()
    record = {
        "id": request.operation_id,
        "operation_id": request.operation_id,
        "payload_hash": payload_hash,
        "page_url": normalize_page_url(request.page_url),
        "page_title": request.page_title,
        "learner_level": learner_level,
        "learner_profile_fingerprint": learner_profile_fingerprint,
        "target_language": target,
        "native_language": native,
        "vocabulary_coverage_percent": vocabulary_coverage_percent,
        "sentence_limit": sentence_limit,
        "sentences_detected": prepared.sentences_detected,
        "source_tokens_detected": prepared.source_tokens_detected,
        "source_tokens_analyzed": prepared.source_tokens_analyzed,
        "source_token_limit": prepared.source_token_limit,
        "status": "content_pending",
        "enqueue_state": "pending",
        "submitted": False,
        "reservation_enabled": reservation_enabled,
        "error": None,
        "requested_at": now,
        "created_at": now,
    }
    if operation:
        record.update(
            {
                "usage_month": operation.month,
                "usage_state": operation.state,
                "quota_plan": operation.plan_id,
                "article_limit": operation.article_limit,
                "chat_limit": operation.chat_limit,
                "cost_micro_usd_limit": operation.cost_micro_usd_limit,
                "rate_card_version": operation.rate_card_version,
                "tokenizer_encoding": operation.tokenizer_encoding,
                "model": operation.model,
                "input_micro_usd_per_million": operation.input_micro_usd_per_million,
                "output_micro_usd_per_million": operation.output_micro_usd_per_million,
                "estimated_cost_micro_usd": operation.reserved_cost_micro_usd,
            }
        )
    elif shadow_enabled:
        record["shadow_usage"] = {
            "operation_id": request.operation_id,
            "meter": "article",
            "pricing_available": usage_meter.pricing_available,
            "model": usage_meter.rate.model,
            "rate_card_version": usage_meter.rate.version,
            "tokenizer_encoding": os.getenv("OPENAI_TOKEN_ENCODING", "o200k_base").strip(),
        }
        if estimated_cost is not None:
            record["shadow_usage"]["estimated_cost_micro_usd"] = estimated_cost
            record["shadow_usage"]["input_micro_usd_per_million"] = (
                usage_meter.rate.input_micro_usd_per_million
            )
            record["shadow_usage"]["output_micro_usd_per_million"] = (
                usage_meter.rate.output_micro_usd_per_million
            )

    creation = repository.create_if_absent(user_id, record)
    record = creation.record
    owns_handoff = creation.created
    if not owns_handoff and record.get("status") == "content_pending":
        takeover = repository.claim_content_handoff(user_id, record)
        record = takeover.record
        owns_handoff = takeover.created
    if not owns_handoff:
        return _to_status_response(record)

    handoff_token = str(record["content_handoff_token"])
    enqueue_attempted = False
    try:
        stored_content = content_store.get(user_id, record["id"])
        if stored_content is None:
            content_written = content_store.put_if_absent(user_id, record["id"], prepared.content)
            if not content_written:
                stored_content = content_store.get(user_id, record["id"])
                if stored_content != prepared.content:
                    raise RuntimeError(
                        "Preload handoff content conflicts with the operation payload."
                    )
        elif stored_content != prepared.content:
            raise RuntimeError("Preload handoff content conflicts with the operation payload.")
        if not repository.mark_content_available(user_id, record["id"], handoff_token):
            return _to_status_response(repository.get_by_id(user_id, record["id"]) or record)
        record = repository.get_by_id(user_id, record["id"]) or record
        if not repository.mark_enqueue_submitting(user_id, record["id"]):
            if repository.fail_content_handoff(
                user_id,
                record["id"],
                handoff_token,
                "The preload job could not be queued. Release is pending.",
            ):
                failed = repository.get_by_id(user_id, record["id"]) or record
                return _to_status_response(
                    _recover_failed_content_handoff(
                        repository, content_store, user_id, failed, usage_meter
                    )
                )
            return _to_status_response(repository.get_by_id(user_id, record["id"]) or record)
        record["enqueue_state"] = "queued_unconfirmed"
        record["submitted"] = True
        usage_context = {
            key: record[key]
            for key in (
                "operation_id",
                "payload_hash",
                "usage_month",
                "quota_plan",
                "article_limit",
                "chat_limit",
                "cost_micro_usd_limit",
                "sentence_limit",
                "source_token_limit",
                "source_tokens_detected",
                "source_tokens_analyzed",
                "rate_card_version",
                "model",
                "input_micro_usd_per_million",
                "output_micro_usd_per_million",
                "estimated_cost_micro_usd",
            )
            if key in record
        }
        if operation:
            enqueue_attempted = True
            job_runner.enqueue(
                user_id,
                record["page_url"],
                record["id"],
                record["learner_profile_fingerprint"],
                usage_context,
            )
        else:
            enqueue_attempted = True
            job_runner.enqueue(
                user_id,
                record["page_url"],
                record["id"],
                record["learner_profile_fingerprint"],
            )
        try:
            confirmed = repository.confirm_enqueued(user_id, record["id"])
        except Exception:
            logger.exception(
                "preload enqueue confirmation failed after submission user=%s preload_id=%s",
                user_id,
                record["id"],
            )
            current = repository.get_by_id(user_id, record["id"])
            return _to_status_response(current or record)
        current = repository.get_by_id(user_id, record["id"])
        if not confirmed:
            logger.warning(
                "preload enqueue confirmation lost race user=%s preload_id=%s",
                user_id,
                record["id"],
            )
            return _to_status_response(current or record)
        record = current or {
            **record,
            "enqueue_state": "queued",
            "submitted": True,
        }
    except Exception:
        if enqueue_attempted:
            logger.exception(
                "preload enqueue outcome is ambiguous; reservation retained user=%s preload_id=%s",
                user_id,
                record["id"],
            )
            current = repository.get_by_id(user_id, record["id"])
            return _to_status_response(current or record)
        if repository.fail_content_handoff(
            user_id,
            record["id"],
            handoff_token,
            "The preload handoff failed. Release is pending.",
        ):
            failed = repository.get_by_id(user_id, record["id"]) or record
            _recover_failed_content_handoff(repository, content_store, user_id, failed, usage_meter)
        else:
            logger.info(
                "preload handoff ownership changed before cleanup user=%s preload_id=%s",
                user_id,
                record["id"],
            )
            current = repository.get_by_id(user_id, record["id"])
            if current is not None:
                return _to_status_response(current)
        raise
    return _to_status_response(record)


class _PreloadHeartbeat:
    def __init__(
        self,
        *,
        repository: PagePreloadRepository,
        meter: UsageMeter | None,
        user_id: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        lease_id: str,
        operation_id: str,
        lease_seconds: int,
    ) -> None:
        self.repository = repository
        self.meter = meter
        self.user_id = user_id
        self.preload_id = preload_id
        self.learner_profile_fingerprint = learner_profile_fingerprint
        self.lease_id = lease_id
        self.operation_id = operation_id
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"preload-heartbeat-{preload_id}",
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
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.lease_seconds)
        try:
            if not self.repository.renew_processing_lease(
                self.user_id,
                self.preload_id,
                self.learner_profile_fingerprint,
                self.lease_id,
                now,
                expires_at,
            ):
                return False
            if self.meter:
                if not self.meter.renew_execution(self.operation_id, self.lease_id, expires_at):
                    return False
                try:
                    self.meter.renew(self.operation_id, expires_at)
                except Exception:
                    logger.warning(
                        "preload usage renewal failed while execution remains owned operation_id=%s",
                        self.operation_id,
                    )
            return True
        except Exception:
            logger.exception(
                "preload heartbeat failed user=%s preload_id=%s",
                self.user_id,
                self.preload_id,
            )
            return False

    def stop_and_verify(self) -> bool:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.lease_seconds))
        if self._thread.is_alive() or self._lost.is_set():
            return False
        return self._renew_once()


def run_preload_job(
    repository: PagePreloadRepository,
    subscription_repository: SubscriptionRepository,
    usage_repository: UsageRepository,
    content_store: PreloadContentStore,
    user_id: str,
    page_url: str,
    preload_id: str,
    learner_profile_fingerprint: str,
    usage_context: dict[str, Any] | None = None,
    admin_activity_repository: AdminActivityRepository | None = None,
    billing_provider_mode: str = "stripe",
) -> None:
    """Run the deferred analysis for a "processing" preload record.

    Loads the record saved by ``submit_preload`` (extraction already done),
    runs split + analyze + study-item selection, and flips the record to
    "ready" with everything a reader needs. Usage is metered here so the
    worker records exactly like the old synchronous path did.

    Idempotent-ish for SQS at-least-once delivery: a record that is already
    ready (or predates the async pipeline) returns without re-running. On
    failure the record is marked "failed" with an English error detail and no
    usage is recorded, so a failed analysis never burns quota.
    """
    record = repository.get_by_id(user_id, preload_id)
    if not record:
        return
    if record.get("status") in ("ready", "failed"):
        record = _retire_terminal_content(
            repository,
            content_store,
            user_id,
            record,
            learner_profile_fingerprint,
        )
        status = "success" if record.get("status") == "ready" else "failed"
        record_terminal_activity(
            admin_activity_repository,
            TerminalActivityOutcome.for_preload(
                user_id=user_id,
                preload_id=preload_id,
                status=status,
                error=RuntimeError("preload_failed") if status == "failed" else None,
                record=record,
            ),
        )
        return

    operation_id = str(record.get("operation_id") or "")
    meter = None
    operation = None
    shadow_context = record.get("shadow_usage")
    shadow_meter = None
    if isinstance(shadow_context, dict):
        shadow_meter = UsageMeter(
            subscription_repository,
            usage_repository,
            user_id,
            rate=ModelRate(
                model=str(shadow_context.get("model") or ""),
                input_micro_usd_per_million=int(
                    shadow_context.get("input_micro_usd_per_million") or 0
                ),
                output_micro_usd_per_million=int(
                    shadow_context.get("output_micro_usd_per_million") or 0
                ),
                version=str(shadow_context.get("rate_card_version") or ""),
            ),
            reservation_enabled=False,
            provider_mode=billing_provider_mode,
        )
    reservation_operation_id = operation_id if record.get("reservation_enabled") else ""
    if not record.get("reservation_enabled") and "reservation_enabled" not in record:
        reservation_operation_id = operation_id if not isinstance(shadow_context, dict) else ""
    if reservation_operation_id:
        rate = ModelRate(
            model=str(record.get("model") or ""),
            input_micro_usd_per_million=int(record.get("input_micro_usd_per_million") or 0),
            output_micro_usd_per_million=int(record.get("output_micro_usd_per_million") or 0),
            version=str(record.get("rate_card_version") or ""),
        )
        meter = UsageMeter(
            subscription_repository,
            usage_repository,
            user_id,
            rate=rate,
            reservation_enabled=True,
            provider_mode=billing_provider_mode,
        )
        operation = meter.get_operation(reservation_operation_id)
        if operation is None:
            raise RuntimeError(
                "Usage operation "
                f"{reservation_operation_id} is missing; refusing provider dispatch."
            )
        if operation.state == "released":
            if record.get("status") not in ("ready", "failed"):
                blocked = dict(record)
                blocked["status"] = "failed"
                blocked["usage_state"] = "released"
                blocked["error"] = (
                    "The usage reservation expired before analysis started. "
                    "Please submit the article again."
                )
                repository.save(user_id, blocked, make_latest=False)
            return
        if operation and operation.state == "finalized":
            if record.get("status") in ("processing", "running"):
                crash_result = meter.get_result(operation_id)
                if crash_result and crash_result.get("kind") == "preload":
                    interrupted = dict(record)
                    interrupted["status"] = "failed"
                    interrupted["usage_state"] = "finalized_conservative"
                    interrupted["error"] = (
                        "Article analysis was interrupted after provider "
                        "dispatch. Please submit it again."
                    )
                    completed = repository.finish_processing(
                        user_id,
                        preload_id,
                        learner_profile_fingerprint,
                        interrupted,
                        lease_id=(
                            str(record.get("lease_id"))
                            if record.get("status") == "running" and record.get("lease_id")
                            else None
                        ),
                        expected_status=str(record.get("status")),
                    )
                    _require_published_transition(repository, user_id, preload_id, completed)
                    _log_recovery_event(
                        "pending_result_repaired",
                        operation_id=operation_id,
                        kind="preload",
                        outcome="interrupted",
                    )
                return
            if record.get("status") == "ready_pending_usage":
                repaired = dict(record)
                repaired["status"] = "ready"
                repaired["usage_state"] = "finalized"
                completed = repository.finish_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    repaired,
                    lease_id=record.get("lease_id"),
                    expected_status="ready_pending_usage",
                )
                _require_published_transition(repository, user_id, preload_id, completed)
                _log_recovery_event(
                    "pending_result_repaired",
                    operation_id=operation_id,
                    kind="preload",
                    outcome="ready",
                )
                _retire_terminal_content(
                    repository,
                    content_store,
                    user_id,
                    repaired,
                    learner_profile_fingerprint,
                )
            elif record.get("status") == "failed_pending_usage":
                repaired = dict(record)
                repaired["status"] = "failed"
                repaired["usage_state"] = "finalized_conservative"
                completed = repository.finish_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    repaired,
                    lease_id=record.get("lease_id"),
                    expected_status="failed_pending_usage",
                )
                _require_published_transition(repository, user_id, preload_id, completed)
                _log_recovery_event(
                    "pending_result_repaired",
                    operation_id=operation_id,
                    kind="preload",
                    outcome="failed",
                )
                _retire_terminal_content(
                    repository,
                    content_store,
                    user_id,
                    repaired,
                    learner_profile_fingerprint,
                )
            return
        if operation.state == "released" and record.get("status") == "failed_pending_usage":
            repaired = dict(record)
            repaired["status"] = "failed"
            repaired["usage_state"] = "released"
            completed = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                repaired,
                lease_id=record.get("lease_id"),
                expected_status="failed_pending_usage",
            )
            _require_published_transition(repository, user_id, preload_id, completed)
            _log_recovery_event(
                "pending_result_repaired",
                operation_id=operation_id,
                kind="preload",
                outcome="released",
            )
            _retire_terminal_content(
                repository,
                content_store,
                user_id,
                repaired,
                learner_profile_fingerprint,
            )
            return
        if (
            operation
            and operation.state == "reserved"
            and record.get("status") in ("ready_pending_usage", "ready")
            and record.get("usage_tally")
        ):
            meter.finalize(
                operation_id,
                record["usage_tally"],
                result_ref=preload_id,
            )
            repaired = dict(record)
            repaired["status"] = "ready"
            repaired["usage_state"] = "finalized"
            completed = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                repaired,
                lease_id=record.get("lease_id"),
                expected_status=str(record.get("status")),
            )
            _require_published_transition(repository, user_id, preload_id, completed)
            _log_recovery_event(
                "pending_result_repaired",
                operation_id=operation_id,
                kind="preload",
                outcome="finalized",
            )
            _retire_terminal_content(
                repository,
                content_store,
                user_id,
                repaired,
                learner_profile_fingerprint,
            )
            return
        if operation.state == "reserved" and record.get("status") == "failed_pending_usage":
            if record.get("failure_settlement") == "finalize_conservative":
                meter.finalize(
                    operation_id,
                    record.get("failure_usage")
                    or {"actual_cost_micro_usd": operation.reserved_cost_micro_usd},
                    result_ref=preload_id,
                )
                usage_state = "finalized_conservative"
            else:
                meter.release(
                    operation_id,
                    str(record.get("failure_reason") or "analysis_failed_before_dispatch"),
                )
                usage_state = "released"
            repaired = dict(record)
            repaired["status"] = "failed"
            repaired["usage_state"] = usage_state
            completed = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                repaired,
                lease_id=record.get("lease_id"),
                expected_status="failed_pending_usage",
            )
            _require_published_transition(repository, user_id, preload_id, completed)
            _log_recovery_event(
                "pending_result_repaired",
                operation_id=operation_id,
                kind="preload",
                outcome="settled_failure",
            )
            _retire_terminal_content(
                repository,
                content_store,
                user_id,
                repaired,
                learner_profile_fingerprint,
            )
            return

    latest = repository.get_by_page_url(user_id, page_url)

    lease_id = generate_uuid7()
    lease_now = datetime.now(UTC)
    lease_seconds = max(1, int(os.getenv("PRELOAD_WORKER_LEASE_SECONDS", "900")))
    lease_expires_at = lease_now + timedelta(seconds=lease_seconds)
    reclaimed_worker_lease = _has_expired_preload_lease(record, lease_now)
    record = repository.claim_processing(
        user_id,
        preload_id,
        learner_profile_fingerprint,
        lease_id=lease_id,
        now=lease_now,
        lease_expires_at=lease_expires_at,
    )
    if not record:
        logger.info(
            "preload job skipped user=%s preload_id=%s: no matching processing record",
            user_id,
            preload_id,
        )
        return
    if reclaimed_worker_lease:
        _log_recovery_event(
            "execution_lease_recovered",
            operation_id=operation_id or preload_id,
            kind="preload",
        )
    if latest and latest.get("id") != preload_id:
        superseded = dict(record)
        superseded["status"] = "failed_pending_usage" if meter else "failed"
        superseded["content_retirement_pending"] = True
        superseded["error"] = "This preload was superseded by a newer request."
        if meter:
            superseded["failure_settlement"] = "release"
            superseded["failure_reason"] = "preload_superseded"
            superseded["usage_state"] = "reserved"
        completed = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            superseded,
            lease_id=lease_id,
        )
        if not completed:
            return
        if meter:
            meter.release(operation_id, "preload_superseded")
            superseded["status"] = "failed"
            superseded["usage_state"] = "released"
            settled = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                superseded,
                lease_id=lease_id,
                expected_status="failed_pending_usage",
            )
            _require_published_transition(repository, user_id, preload_id, settled)
        _retire_terminal_content(
            repository,
            content_store,
            user_id,
            superseded,
            learner_profile_fingerprint,
        )
        return
    if meter:
        execution_status = meter.claim_execution(
            operation_id,
            lease_id,
            lease_now,
            lease_expires_at,
        )
        if not execution_status:
            retryable = dict(record)
            retryable["status"] = "processing"
            repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                retryable,
                lease_id=lease_id,
            )
            return
        durable_result = meter.get_result(operation_id)
        if (
            durable_result
            and durable_result.get("kind") == "preload"
            and durable_result.get("state") in ("dispatching", "completed")
        ):
            stored_usage = dict(durable_result.get("usage") or {})
            if durable_result.get("state") == "dispatching":
                stored_usage.setdefault(
                    "actual_cost_micro_usd",
                    operation.reserved_cost_micro_usd,
                )
            try:
                meter.finalize(
                    operation_id,
                    stored_usage,
                    result_ref=preload_id,
                )
                interrupted = dict(record)
                interrupted["status"] = "failed"
                interrupted["usage_state"] = (
                    "finalized_conservative"
                    if durable_result.get("state") == "dispatching"
                    else "finalized"
                )
                interrupted["error"] = (
                    "Article analysis was interrupted after provider "
                    "dispatch. Please submit it again."
                )
                completed = repository.finish_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    interrupted,
                    lease_id=lease_id,
                )
                _require_published_transition(repository, user_id, preload_id, completed)
            finally:
                meter.release_execution(operation_id, lease_id)
            return
        try:
            operation = meter.renew(operation_id, lease_expires_at)
        except UsageOperationStateError:
            blocked = dict(record)
            blocked["status"] = "failed"
            blocked["usage_state"] = "released"
            blocked["error"] = (
                "The usage reservation expired before analysis started. "
                "Please submit the article again."
            )
            repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                blocked,
                lease_id=lease_id,
            )
            meter.release_execution(operation_id, lease_id)
            return
        except Exception:
            retryable = dict(record)
            retryable["status"] = "processing"
            repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                retryable,
                lease_id=lease_id,
            )
            meter.release_execution(operation_id, lease_id)
            raise

    # The raw text lives in the transient content store, keyed by (user, operation).
    # Fall back to an inline "content" field only for legacy in-flight records
    # written by the old code (which stored it on the record). If neither has
    # it, the payload was lost or expired: mark the record failed rather than
    # analyze empty text or crash the batch.
    content = content_store.get(user_id, preload_id) or record.get("content")
    if not content:
        failed = dict(record)
        failed["status"] = "failed_pending_usage" if meter else "failed"
        failed["content_retirement_pending"] = True
        failed["error"] = (
            "The article text is no longer available. Please reload the page to try again."
        )
        if meter:
            failed["failure_settlement"] = "release"
            failed["failure_reason"] = "content_missing"
            failed["usage_state"] = "reserved"
        completed = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            failed,
            lease_id=lease_id,
        )
        if completed:
            if meter:
                meter.release(operation_id, "content_missing")
                failed["status"] = "failed"
                failed["usage_state"] = "released"
                settled = repository.finish_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    failed,
                    lease_id=lease_id,
                    expected_status="failed_pending_usage",
                )
                _require_published_transition(repository, user_id, preload_id, settled)
            _retire_terminal_content(
                repository,
                content_store,
                user_id,
                failed,
                learner_profile_fingerprint,
            )
        if meter:
            meter.release_execution(operation_id, lease_id)
        logger.warning(
            "preload job: no content in store user=%s url=%s", user_id, normalize_page_url(page_url)
        )
        return

    guard = (
        None
        if meter
        else build_guard(
            subscription_repository,
            usage_repository,
            user_id,
            provider_mode=billing_provider_mode,
        )
    )
    tally = (
        UsageTally(rate=meter.rate)
        if meter
        else (UsageTally(rate=shadow_meter.rate) if shadow_meter else UsageTally())
    )
    if meter:
        _configure_preload_dispatch_marker(meter, operation, tally)
    page_title = record.get("page_title")
    sentence_limit = record.get("sentence_limit")
    vocabulary_coverage_percent = _resolve_vocabulary_coverage_percent(
        record.get("vocabulary_coverage_percent")
    )
    target, native = _resolve_language_pair(
        record.get("target_language"), record.get("native_language")
    )

    heartbeat = _PreloadHeartbeat(
        repository=repository,
        meter=meter,
        user_id=user_id,
        preload_id=preload_id,
        learner_profile_fingerprint=learner_profile_fingerprint,
        lease_id=lease_id,
        operation_id=operation_id,
        lease_seconds=lease_seconds,
    )
    started = time.perf_counter()
    provider_error = None
    heartbeat.start()
    try:
        sentences = _split_sentences(
            content, page_title=page_title, max_sentences=sentence_limit, tally=tally
        )
        split_done = time.perf_counter()

        summary, topics, indexed_sentences = _analyze_sentences(
            sentences,
            page_title=page_title,
            vocabulary_coverage_percent=vocabulary_coverage_percent,
            target=target,
            native=native,
            learner_level=record.get("learner_level"),
            tally=tally,
        )
        analyze_done = time.perf_counter()

        study_items, vocabulary_coverage = _extract_study_items(
            indexed_sentences,
            vocabulary_coverage_percent=vocabulary_coverage_percent,
        )
    except Exception as exc:  # noqa: BLE001 - settlement follows ownership check
        provider_error = exc
    finally:
        try:
            if meter and (provider_error is None or _dispatch_was_attempted(tally, provider_error)):
                durable_usage = (
                    _settlement_usage(tally, operation)
                    if provider_error is None
                    else {"actual_cost_micro_usd": (operation.reserved_cost_micro_usd)}
                )
                meter.save_result(
                    operation_id,
                    {
                        "kind": "preload",
                        "state": "completed",
                        "usage": durable_usage,
                    },
                )
        finally:
            owns_publication = heartbeat.stop_and_verify()
            if meter:
                meter.release_execution(operation_id, lease_id)

    if not owns_publication:
        logger.info(
            "preload heartbeat ownership verification failed user=%s preload_id=%s; attempting conditional publication",
            user_id,
            preload_id,
        )

    if provider_error is not None:
        exc = provider_error
        failed = dict(record)
        failed["status"] = "failed_pending_usage" if meter else "failed"
        failed["content_retirement_pending"] = True
        failed["error"] = str(exc) or "Article analysis failed. Please try again."
        if meter:
            if _dispatch_was_attempted(tally, exc):
                failed["failure_settlement"] = "finalize_conservative"
                failed["failure_usage"] = {
                    "actual_cost_micro_usd": operation.reserved_cost_micro_usd,
                }
            else:
                failed["failure_settlement"] = "release"
                failed["failure_reason"] = "analysis_failed_before_dispatch"
            failed["usage_state"] = "reserved"
        completed = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            failed,
            lease_id=lease_id,
        )
        if completed and meter:
            if failed["failure_settlement"] == "finalize_conservative":
                meter.finalize(
                    operation_id,
                    failed["failure_usage"],
                    result_ref=preload_id,
                )
                failed["usage_state"] = "finalized_conservative"
            else:
                meter.release(operation_id, failed["failure_reason"])
                failed["usage_state"] = "released"
            failed["status"] = "failed"
            settled = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                failed,
                lease_id=lease_id,
                expected_status="failed_pending_usage",
            )
            _require_published_transition(repository, user_id, preload_id, settled)
        if shadow_meter:
            shadow_meter.observe_shadow(
                str(shadow_context.get("operation_id") or preload_id),
                "article",
                shadow_context.get("estimated_cost_micro_usd"),
                _shadow_usage(tally),
                outcome=(
                    "conservative_failure"
                    if _dispatch_was_attempted(tally, exc)
                    else "failed_before_dispatch"
                ),
            )
        if completed:
            failed = _retire_terminal_content(
                repository,
                content_store,
                user_id,
                failed,
                learner_profile_fingerprint,
            )
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome.for_preload(
                    user_id=user_id,
                    preload_id=preload_id,
                    status="failed",
                    error=exc,
                    record=failed,
                    tally=tally,
                ),
            )
        logger.warning("preload job failed user=%s url=%s: %s", user_id, page_url, exc)
        return

    logger.info(
        "preload job url=%s sentences=%d split=%.1fs analyze=%.1fs study_items=%.1fs total=%.1fs",
        normalize_page_url(page_url),
        len(sentences),
        split_done - started,
        analyze_done - split_done,
        time.perf_counter() - analyze_done,
        time.perf_counter() - started,
    )

    ready = dict(record)
    # Drop any legacy inline content: the ready record must not carry it.
    ready.pop("content", None)
    ready.update(
        {
            "summary": summary,
            "topics": topics,
            "sentences": indexed_sentences,
            "study_items": study_items,
            "vocabulary_coverage": vocabulary_coverage,
            "sentences_detected": record.get("sentences_detected")
            or _estimate_sentence_count(content),
            "created_at": datetime.now(UTC).isoformat(),
            "status": "ready_pending_usage" if meter else "ready",
            "error": None,
            "content_retirement_pending": True,
        }
    )
    if meter:
        ready["usage_tally"] = _settlement_usage(tally, operation)
        ready["usage_state"] = "reserved"
    try:
        completed = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            ready,
            lease_id=lease_id,
        )
    except PreloadResultTooLarge as exc:
        failed = dict(record)
        failed["status"] = "failed_pending_usage" if meter else "failed"
        failed["error"] = str(exc)
        failed["content_retirement_pending"] = True
        if meter:
            failed["failure_settlement"] = "finalize_conservative"
            failed["failure_usage"] = {
                "actual_cost_micro_usd": operation.reserved_cost_micro_usd,
            }
            failed["usage_state"] = "reserved"
        published = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            failed,
            lease_id=lease_id,
        )
        if published and meter:
            meter.finalize(
                operation_id,
                failed["failure_usage"],
                result_ref=preload_id,
            )
            failed["status"] = "failed"
            failed["usage_state"] = "finalized_conservative"
            settled = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                failed,
                lease_id=lease_id,
                expected_status="failed_pending_usage",
            )
            _require_published_transition(repository, user_id, preload_id, settled)
        if published:
            failed = _retire_terminal_content(
                repository,
                content_store,
                user_id,
                failed,
                learner_profile_fingerprint,
            )
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome.for_preload(
                    user_id=user_id,
                    preload_id=preload_id,
                    status="failed",
                    error=exc,
                    record=failed,
                    tally=tally,
                ),
            )
        return
    if not completed:
        logger.info(
            "preload job result discarded user=%s preload_id=%s: record was superseded",
            user_id,
            preload_id,
        )
        return
    if meter:
        meter.finalize(operation_id, ready["usage_tally"], result_ref=preload_id)
        ready["status"] = "ready"
        ready["usage_state"] = "finalized"
        settled = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            ready,
            lease_id=lease_id,
            expected_status="ready_pending_usage",
        )
        _require_published_transition(repository, user_id, preload_id, settled)
    elif guard:
        guard.record_article(tokens=tally.total_tokens)
    if shadow_meter:
        shadow_meter.observe_shadow(
            str(shadow_context.get("operation_id") or preload_id),
            "article",
            shadow_context.get("estimated_cost_micro_usd"),
            _shadow_usage(tally),
            outcome="succeeded",
        )
    record_terminal_activity(
        admin_activity_repository,
        TerminalActivityOutcome.for_preload(
            user_id=user_id,
            preload_id=preload_id,
            status="success",
            record=ready,
            tally=tally,
        ),
    )

    _retire_terminal_content(
        repository,
        content_store,
        user_id,
        ready,
        learner_profile_fingerprint,
    )
