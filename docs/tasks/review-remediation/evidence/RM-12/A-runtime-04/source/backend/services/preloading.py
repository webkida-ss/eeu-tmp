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
from repositories.usage_repository import (
    UsageOperationConflict,
    UsageOperationStateError,
    UsageRepository,
)
from schemas import (
    PagePreloadRequest,
    PagePreloadStatusResponse,
)
from storage.preload_content_store import PreloadContentStore

from services.admin_activity import TerminalActivityOutcome, record_terminal_activity
from services.entitlements import (
    EffectiveProcessingAllowance,
    EntitlementError,
    EntitlementGuard,
    build_guard,
    resolve_effective_processing_allowance,
)
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


def _durable_preload_meter(usage_meter: UsageMeter) -> UsageMeter:
    """Upgrade one new preload without changing the caller's shared disabled meter."""
    if usage_meter.durable_shadow:
        return usage_meter
    durable = UsageMeter(
        usage_meter.subscription_repository,
        usage_meter.usage_repository,
        usage_meter.user_id,
        rate=usage_meter.rate,
        now=usage_meter.now,
        plan_loader=usage_meter.plan_loader,
        reservation_ttl_seconds=usage_meter.reservation_ttl_seconds,
        reservation_enabled=False,
        durable_shadow=True,
        provider_mode=usage_meter.provider_mode,
    )
    durable.pricing_available = usage_meter.pricing_available
    return durable


def _allowance_with_saved_preload_caps(
    allowance: EffectiveProcessingAllowance,
    record: dict[str, Any],
) -> EffectiveProcessingAllowance:
    """Use positive caps saved with an older preload without changing its month."""
    sentence_limit = record.get("sentence_limit")
    source_token_limit = record.get("source_token_limit")
    return EffectiveProcessingAllowance(
        month=allowance.month,
        sentences_per_article=(
            sentence_limit
            if isinstance(sentence_limit, int)
            and not isinstance(sentence_limit, bool)
            and sentence_limit > 0
            else allowance.sentences_per_article
        ),
        source_tokens_per_article=(
            source_token_limit
            if isinstance(source_token_limit, int)
            and not isinstance(source_token_limit, bool)
            and source_token_limit > 0
            else allowance.source_tokens_per_article
        ),
    )


def _complete_saved_preload_allowance(
    record: dict[str, Any] | None,
    month: str,
) -> EffectiveProcessingAllowance | None:
    if record is None:
        return None
    sentence_limit = record.get("sentence_limit")
    source_token_limit = record.get("source_token_limit")
    if (
        not isinstance(sentence_limit, int)
        or isinstance(sentence_limit, bool)
        or sentence_limit <= 0
        or not isinstance(source_token_limit, int)
        or isinstance(source_token_limit, bool)
        or source_token_limit <= 0
    ):
        return None
    return EffectiveProcessingAllowance(
        month=month,
        sentences_per_article=sentence_limit,
        source_tokens_per_article=source_token_limit,
    )


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
    tally.set_dispatch_callback(meter.dispatch_authorizer(operation.operation_id, marker))


def _finalize_dispatch_evidence(
    meter: UsageMeter,
    operation: Any,
    *,
    result_ref: str,
) -> str:
    """Settle durable provider evidence without relying on private results."""
    usage = operation.dispatch_usage or {"actual_cost_micro_usd": operation.reserved_cost_micro_usd}
    completeness = (
        "measured" if operation.dispatch_usage_completeness == "measured" else "conservative"
    )
    meter.finalize(
        operation.operation_id,
        usage,
        result_ref=result_ref,
        evidence_completeness=completeness,
    )
    return "finalized" if completeness == "measured" else "finalized_conservative"


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
    if usage_meter and usage_meter.durable_shadow and operation_id:
        operation = usage_meter.get_operation(operation_id)
        if operation is None:
            return record
        try:
            if operation.state == "finalized" or operation.shadow_pending_outcome:
                operation = _settle_durable_shadow(usage_meter, operation_id)
            else:
                outcome = (
                    "failed_after_dispatch"
                    if operation.dispatch_evidence_state in ("dispatched", "completed")
                    else "failed_before_dispatch"
                )
                operation = _settle_durable_shadow(
                    usage_meter,
                    operation_id,
                    outcome=outcome,
                    result_ref=str(record.get("id") or operation_id),
                )
        except Exception:  # noqa: BLE001 - retain retryable handoff ownership
            logger.exception(
                "durable shadow handoff settlement failed operation_id=%s", operation_id
            )
            return record
        recovered = {
            **record,
            "status": "failed",
            "usage_state": "finalized",
            "shadow_outcome": operation.shadow_outcome,
            "content_retirement_pending": True,
        }
        completed = repository.finish_processing(
            user_id,
            str(record["id"]),
            str(record.get("learner_profile_fingerprint") or ""),
            recovered,
            expected_status="failed_pending_release",
        )
        if not completed:
            return repository.get_by_id(user_id, str(record["id"])) or record
        return _retire_terminal_content(
            repository,
            content_store,
            user_id,
            recovered,
            str(record.get("learner_profile_fingerprint") or ""),
        )
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
    if shadow_enabled and usage_meter and not usage_meter.durable_shadow:
        usage_meter = _durable_preload_meter(usage_meter)
    durable_shadow = bool(shadow_enabled and usage_meter and usage_meter.durable_shadow)
    payload_hash = canonical_payload_hash(request, exclude={"operation_id"})
    requested_record = repository.get_by_id(user_id, request.operation_id)
    if requested_record and (
        requested_record.get("payload_hash") != payload_hash
        or requested_record.get("learner_profile_fingerprint") != learner_profile_fingerprint
    ):
        raise EntitlementError(
            "Operation ID was already used for a different payload.",
            code="operation_payload_conflict",
            status_code=409,
        )
    if (
        requested_record
        and requested_record.get("status") == "failed_pending_release"
        and not reservation_enabled
    ):
        return _to_status_response(
            _recover_failed_content_handoff(
                repository,
                content_store,
                user_id,
                requested_record,
                usage_meter,
            )
        )
    if requested_record and requested_record.get("status") == "ready" and usage_meter:
        operation = usage_meter.get_operation(request.operation_id)
        if operation is None or operation.state == "finalized":
            return _to_status_response(requested_record)
    existing = repository.get_by_page_url(user_id, request.page_url)
    if (
        existing
        and existing.get("operation_id") == request.operation_id
        and (
            existing.get("payload_hash") != payload_hash
            or existing.get("learner_profile_fingerprint") != learner_profile_fingerprint
        )
    ):
        raise EntitlementError(
            "Operation ID was already used for a different payload.",
            code="operation_payload_conflict",
            status_code=409,
        )
    if (
        existing
        and _is_fresh_processing(existing)
        and not reservation_enabled
        and not durable_shadow
    ):
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
    if usage_meter:
        persisted_operation = usage_meter.get_operation(request.operation_id)
        allowance = _complete_saved_preload_allowance(
            requested_record,
            persisted_operation.month if persisted_operation is not None else "",
        )
        if allowance is None:
            try:
                allowance = usage_meter.processing_allowance(request.operation_id)
            except UsageOperationStateError as exc:
                raise EntitlementError(
                    "Saved processing allowance is unavailable.",
                    code="operation_context_unavailable",
                    status_code=409,
                ) from exc
    elif isinstance(guard, EntitlementGuard):
        allowance = resolve_effective_processing_allowance(guard)
    elif guard:
        # Plan-only guards retain their declared processing caps.
        allowance = EffectiveProcessingAllowance(
            month="",
            sentences_per_article=guard.plan.sentences_per_article,
            source_tokens_per_article=guard.plan.source_tokens_per_article,
        )
    else:
        allowance = None
    if (
        requested_record
        and allowance
        and not _complete_saved_preload_allowance(requested_record, allowance.month)
    ):
        allowance = _allowance_with_saved_preload_caps(allowance, requested_record)
    sentence_limit = allowance.sentences_per_article if allowance else None
    source_token_limit = allowance.source_tokens_per_article if allowance else None
    prepared = _prepare_article_content(
        content,
        sentence_limit=sentence_limit,
        source_token_limit=source_token_limit,
    )

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
    if reservation_enabled or durable_shadow:
        try:
            operation = usage_meter.reserve(
                request.operation_id,
                payload_hash,
                "article",
                estimated_cost,
                allowance=allowance,
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
        canonical_allowance = _complete_saved_preload_allowance(requested_record, operation.month)
        if canonical_allowance is None:
            try:
                canonical_allowance = usage_meter.processing_allowance(operation.operation_id)
            except UsageOperationStateError as exc:
                raise EntitlementError(
                    "Saved processing allowance is unavailable.",
                    code="operation_context_unavailable",
                    status_code=409,
                ) from exc
        if requested_record and not _complete_saved_preload_allowance(
            requested_record, operation.month
        ):
            canonical_allowance = _allowance_with_saved_preload_caps(
                canonical_allowance,
                requested_record,
            )
        if allowance != canonical_allowance:
            # A concurrent same-operation reservation won after this submit
            # prepared its input. Its month and caps are immutable, so rebuild
            # before claiming any page or content state.
            allowance = canonical_allowance
            sentence_limit = allowance.sentences_per_article
            source_token_limit = allowance.source_tokens_per_article
            prepared = _prepare_article_content(
                content,
                sentence_limit=sentence_limit,
                source_token_limit=source_token_limit,
            )
            estimated_cost = estimate() if reservation_enabled else _shadow_estimate(estimate)
        operation_record = repository.get_by_id(user_id, operation.operation_id)
        if (
            reservation_enabled
            and operation_record
            and operation_record.get("status") == "failed_pending_release"
        ):
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
            and existing.get("status") != "content_pending"
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
        "accounting_mode": "shadow" if durable_shadow else "enforced",
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
                "accounting_mode": operation.accounting_mode,
                "pricing_available": operation.pricing_available,
            }
        )
    if durable_shadow:
        record["shadow_version"] = 1
        record["shadow_usage"] = {
            "operation_id": request.operation_id,
            "meter": "article",
            "pricing_available": operation.pricing_available,
            "model": operation.model,
            "rate_card_version": operation.rate_card_version,
            "tokenizer_encoding": operation.tokenizer_encoding,
            "estimated_cost_micro_usd": operation.reserved_cost_micro_usd,
            "input_micro_usd_per_million": operation.input_micro_usd_per_million,
            "output_micro_usd_per_million": operation.output_micro_usd_per_million,
        }
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
                "accounting_mode",
                "shadow_version",
                "pricing_available",
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
            current = repository.get_by_id(user_id, record["id"])
            if (
                current
                and current.get("status") == "failed_pending_release"
                and current.get("content_handoff_token") == handoff_token
            ):
                raise
            logger.info(
                "preload handoff ownership changed before cleanup user=%s preload_id=%s",
                user_id,
                record["id"],
            )
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


def _durable_shadow_meter(
    subscription_repository: SubscriptionRepository,
    usage_repository: UsageRepository,
    user_id: str,
    record: dict[str, Any],
    billing_provider_mode: str,
) -> UsageMeter | None:
    """Recreate the pinned durable-shadow meter from the submitted record."""
    context = record.get("shadow_usage")
    if not isinstance(context, dict) or record.get("shadow_version") != 1:
        return None
    return UsageMeter(
        subscription_repository,
        usage_repository,
        user_id,
        rate=ModelRate(
            model=str(context.get("model") or ""),
            input_micro_usd_per_million=int(context.get("input_micro_usd_per_million") or 0),
            output_micro_usd_per_million=int(context.get("output_micro_usd_per_million") or 0),
            version=str(context.get("rate_card_version") or ""),
        ),
        reservation_enabled=False,
        durable_shadow=True,
        provider_mode=billing_provider_mode,
    )


def _shadow_ready_payload(
    record: dict[str, Any],
    *,
    content: str,
    summary: str,
    topics: list[Any],
    sentences: list[Any],
    study_items: list[Any],
    vocabulary_coverage: dict[str, Any],
) -> dict[str, Any]:
    """Build the private, validated result needed to repair ready publication."""
    return {
        "summary": summary,
        "topics": topics,
        "sentences": sentences,
        "study_items": study_items,
        "vocabulary_coverage": vocabulary_coverage,
        "sentences_detected": record.get("sentences_detected") or _estimate_sentence_count(content),
        "created_at": datetime.now(UTC).isoformat(),
    }


def _shadow_ready_record(record: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Build the exact ready representation before its immutable success decision."""
    ready = dict(record)
    ready.pop("content", None)
    for field in tuple(ready):
        if field.startswith("shadow_pending_") or field.startswith("_claimed_"):
            ready.pop(field)
    ready.update(response)
    ready.update(
        {
            "status": "ready",
            "error": None,
            "content_retirement_pending": True,
            "accounting_mode": "shadow",
            "shadow_version": 1,
            "usage_state": "finalized",
            "shadow_outcome": "success",
        }
    )
    return ready


def _shadow_unavailable_record(record: dict[str, Any]) -> dict[str, Any]:
    """Publish a bounded failure when a settled response cannot be represented."""
    failed = dict(record)
    failed.pop("content", None)
    for field in tuple(failed):
        if (
            field.startswith("shadow_pending_")
            or field.startswith("_claimed_")
            or field
            in {
                "summary",
                "topics",
                "sentences",
                "study_items",
                "vocabulary_coverage",
            }
        ):
            failed.pop(field)
    failed.update(
        {
            "status": "failed",
            "error": (
                "The saved analysis result is no longer available. Please submit the article again."
            ),
            "content_retirement_pending": True,
        }
    )
    return failed


def _durable_shadow_usage(tally: UsageTally, operation: Any) -> dict[str, Any]:
    """Use exact measured cost, preserving a floor only for uncertain usage."""
    usage = _settlement_usage(tally, operation)
    snapshot = tally.snapshot()
    if snapshot.missing_usage or operation.pricing_available is not True:
        usage["actual_cost_micro_usd"] = max(
            int(usage.get("actual_cost_micro_usd") or 0),
            int(snapshot.cost_micro_usd or 0),
            int(operation.reserved_cost_micro_usd),
        )
    else:
        usage["actual_cost_micro_usd"] = int(snapshot.cost_micro_usd or 0)
    return usage


def _valid_shadow_ready_payload(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a complete private response, without treating TTL expiry as success."""
    if not isinstance(result, dict) or result.get("kind") != "preload":
        return None
    if result.get("state") != "completed" or not isinstance(result.get("response"), dict):
        return None
    response = result["response"]
    required = ("summary", "topics", "sentences", "study_items", "vocabulary_coverage")
    if not all(field in response for field in required):
        return None
    if not isinstance(response["summary"], str):
        return None
    if not all(
        isinstance(response[field], list) for field in ("topics", "sentences", "study_items")
    ):
        return None
    if not isinstance(response["vocabulary_coverage"], dict):
        return None
    return dict(response)


def _finish_durable_shadow_publication(
    repository: PagePreloadRepository,
    content_store: PreloadContentStore,
    meter: UsageMeter,
    user_id: str,
    preload_id: str,
    learner_profile_fingerprint: str,
    record: dict[str, Any],
    operation: Any,
    *,
    expected_status: str,
    lease_id: str | None,
    admin_activity_repository: AdminActivityRepository | None,
    tally: UsageTally | None = None,
) -> bool:
    """Publish only a settled canonical shadow outcome owned by this record."""
    if operation.state != "finalized" or not operation.shadow_outcome:
        return False
    private_result = meter.get_result(operation.operation_id)
    response = _valid_shadow_ready_payload(private_result)
    is_success = operation.shadow_outcome == "success" and response is not None
    terminal = dict(record)
    terminal.pop("content", None)
    if is_success:
        terminal = _shadow_ready_record(record, response)
        try:
            repository.validate_publication(user_id, terminal)
        except PreloadResultTooLarge:
            # The accounting outcome is immutable already. Avoid publishing an
            # oversized private response while retaining its canonical usage.
            is_success = False
            terminal = _shadow_unavailable_record(record)
    else:
        if operation.shadow_outcome == "success":
            terminal = _shadow_unavailable_record(record)
        else:
            terminal.update(
                {
                    "status": "failed",
                    "error": "Article analysis failed. Please try again.",
                    "content_retirement_pending": True,
                }
            )
    terminal["accounting_mode"] = "shadow"
    terminal["shadow_version"] = 1
    terminal["usage_state"] = "finalized"
    terminal["shadow_outcome"] = operation.shadow_outcome
    try:
        completed = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            terminal,
            lease_id=lease_id,
            expected_status=expected_status,
        )
    except PreloadResultTooLarge:
        if not is_success:
            raise
        # The adapter remains authoritative at the write boundary. A late
        # size rejection may only downgrade publication, never its settlement.
        is_success = False
        terminal = _shadow_unavailable_record(record)
        terminal["accounting_mode"] = "shadow"
        terminal["shadow_version"] = 1
        terminal["usage_state"] = "finalized"
        terminal["shadow_outcome"] = operation.shadow_outcome
        completed = repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            terminal,
            lease_id=lease_id,
            expected_status=expected_status,
        )
    if not completed:
        return False
    terminal = _retire_terminal_content(
        repository,
        content_store,
        user_id,
        terminal,
        learner_profile_fingerprint,
    )
    record_terminal_activity(
        admin_activity_repository,
        TerminalActivityOutcome.for_preload(
            user_id=user_id,
            preload_id=preload_id,
            status="success" if is_success else "failed",
            error=None if is_success else RuntimeError("preload_failed"),
            record=terminal,
            tally=tally,
        ),
    )
    return True


def _settle_durable_shadow(
    meter: UsageMeter,
    operation_id: str,
    *,
    outcome: str | None = None,
    result_ref: str | None = None,
) -> Any:
    """Persist one outcome, or recover and settle the canonical winner."""
    operation = meter.get_operation(operation_id)
    if operation is None:
        raise UsageOperationStateError("Durable shadow operation is missing")
    if operation.state == "finalized":
        return operation
    if not operation.shadow_pending_outcome:
        if outcome is None:
            raise UsageOperationStateError("Durable shadow settlement is not prepared")
        try:
            operation = meter.prepare_shadow_settlement(
                operation_id,
                outcome=outcome,  # type: ignore[arg-type]
                result_ref=result_ref,
            )
        except UsageOperationConflict:
            operation = meter.get_operation(operation_id)
            if operation is None:
                raise
    if operation.state != "finalized":
        operation = meter.settle_shadow(operation_id)
    return operation


def _fail_unrecoverable_shadow_record(
    repository: PagePreloadRepository,
    content_store: PreloadContentStore,
    user_id: str,
    preload_id: str,
    learner_profile_fingerprint: str,
    record: dict[str, Any],
) -> None:
    """Fail old in-flight shadow records rather than inventing accounting evidence."""
    status = str(record.get("status") or "")
    lease_id: str | None = None
    if status == "running":
        now = datetime.now(UTC)
        if not _has_expired_preload_lease(record, now):
            return
        lease_id = generate_uuid7()
        record = (
            repository.claim_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                lease_id=lease_id,
                now=now,
                lease_expires_at=now
                + timedelta(seconds=max(1, int(os.getenv("PRELOAD_WORKER_LEASE_SECONDS", "900")))),
            )
            or record
        )
        if record.get("status") != "running" or record.get("lease_id") != lease_id:
            return
        status = "running"
    if status != "processing" and status != "running":
        return
    failed = dict(record)
    failed.update(
        {
            "status": "failed",
            "error": "This legacy shadow preload cannot be recovered safely.",
            "content_retirement_pending": True,
        }
    )
    if repository.finish_processing(
        user_id,
        preload_id,
        learner_profile_fingerprint,
        failed,
        lease_id=lease_id,
        expected_status=status,
    ):
        _retire_terminal_content(
            repository,
            content_store,
            user_id,
            failed,
            learner_profile_fingerprint,
        )


def _run_durable_shadow_preload_job(
    repository: PagePreloadRepository,
    subscription_repository: SubscriptionRepository,
    usage_repository: UsageRepository,
    content_store: PreloadContentStore,
    user_id: str,
    page_url: str,
    preload_id: str,
    learner_profile_fingerprint: str,
    record: dict[str, Any],
    *,
    admin_activity_repository: AdminActivityRepository | None,
    billing_provider_mode: str,
) -> None:
    """Run one durable shadow preload without the legacy additive shadow writes."""
    meter = _durable_shadow_meter(
        subscription_repository,
        usage_repository,
        user_id,
        record,
        billing_provider_mode,
    )
    operation_id = str(record.get("operation_id") or "")
    operation = meter.get_operation(operation_id) if meter and operation_id else None
    if meter is None or operation is None or operation.accounting_mode != "shadow":
        _fail_unrecoverable_shadow_record(
            repository,
            content_store,
            user_id,
            preload_id,
            learner_profile_fingerprint,
            record,
        )
        return

    status = str(record.get("status") or "")
    if status in ("ready_pending_usage", "failed_pending_usage"):
        intended_outcome = record.get("shadow_pending_outcome")
        if intended_outcome not in (
            "success",
            "failed_before_dispatch",
            "failed_after_dispatch",
        ):
            return
        if (
            intended_outcome == "success"
            and _valid_shadow_ready_payload(meter.get_result(operation_id)) is None
        ):
            intended_outcome = "failed_after_dispatch"
        try:
            operation = _settle_durable_shadow(
                meter,
                operation_id,
                outcome=intended_outcome,
                result_ref=preload_id,
            )
        except Exception:  # noqa: BLE001 - pending state remains retryable
            logger.exception(
                "durable shadow settlement recovery failed operation_id=%s", operation_id
            )
            return
        _finish_durable_shadow_publication(
            repository,
            content_store,
            meter,
            user_id,
            preload_id,
            learner_profile_fingerprint,
            record,
            operation,
            expected_status=status,
            lease_id=None,
            admin_activity_repository=admin_activity_repository,
        )
        return

    lease_id = generate_uuid7()
    lease_now = datetime.now(UTC)
    lease_seconds = max(1, int(os.getenv("PRELOAD_WORKER_LEASE_SECONDS", "900")))
    lease_expires_at = lease_now + timedelta(seconds=lease_seconds)
    record = repository.claim_processing(
        user_id,
        preload_id,
        learner_profile_fingerprint,
        lease_id=lease_id,
        now=lease_now,
        lease_expires_at=lease_expires_at,
    )
    if not record:
        return
    operation = meter.get_operation(operation_id)
    if operation is None:
        _fail_unrecoverable_shadow_record(
            repository,
            content_store,
            user_id,
            preload_id,
            learner_profile_fingerprint,
            record,
        )
        return
    execution_status = meter.claim_execution(operation_id, lease_id, lease_now, lease_expires_at)
    if not execution_status:
        repository.finish_processing(
            user_id,
            preload_id,
            learner_profile_fingerprint,
            {**record, "status": "processing"},
            lease_id=lease_id,
        )
        return
    try:
        if operation.state == "finalized" or operation.shadow_pending_outcome:
            operation = _settle_durable_shadow(meter, operation_id)
            _finish_durable_shadow_publication(
                repository,
                content_store,
                meter,
                user_id,
                preload_id,
                learner_profile_fingerprint,
                record,
                operation,
                expected_status="running",
                lease_id=lease_id,
                admin_activity_repository=admin_activity_repository,
            )
            return

        if operation.dispatch_evidence_state in ("dispatched", "completed"):
            retained_response = _valid_shadow_ready_payload(meter.get_result(operation_id))
            outcome = "success" if retained_response is not None else "failed_after_dispatch"
            operation = _settle_durable_shadow(
                meter,
                operation_id,
                outcome=outcome,
                result_ref=preload_id,
            )
            _finish_durable_shadow_publication(
                repository,
                content_store,
                meter,
                user_id,
                preload_id,
                learner_profile_fingerprint,
                record,
                operation,
                expected_status="running",
                lease_id=lease_id,
                admin_activity_repository=admin_activity_repository,
            )
            return

        content = content_store.get(user_id, preload_id) or record.get("content")
        if not content:
            operation = _settle_durable_shadow(
                meter,
                operation_id,
                outcome="failed_before_dispatch",
                result_ref=preload_id,
            )
            _finish_durable_shadow_publication(
                repository,
                content_store,
                meter,
                user_id,
                preload_id,
                learner_profile_fingerprint,
                record,
                operation,
                expected_status="running",
                lease_id=lease_id,
                admin_activity_repository=admin_activity_repository,
            )
            return

        tally = UsageTally(rate=meter.rate)
        _configure_preload_dispatch_marker(meter, operation, tally)
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
        heartbeat.start()
        provider_error: Exception | None = None
        try:
            sentences = _split_sentences(
                content,
                page_title=record.get("page_title"),
                max_sentences=record.get("sentence_limit"),
                tally=tally,
            )
            summary, topics, indexed_sentences = _analyze_sentences(
                sentences,
                page_title=record.get("page_title"),
                vocabulary_coverage_percent=_resolve_vocabulary_coverage_percent(
                    record.get("vocabulary_coverage_percent")
                ),
                target=_resolve_language_pair(
                    record.get("target_language"), record.get("native_language")
                )[0],
                native=_resolve_language_pair(
                    record.get("target_language"), record.get("native_language")
                )[1],
                learner_level=record.get("learner_level"),
                tally=tally,
            )
            study_items, vocabulary_coverage = _extract_study_items(
                indexed_sentences,
                vocabulary_coverage_percent=_resolve_vocabulary_coverage_percent(
                    record.get("vocabulary_coverage_percent")
                ),
            )
            payload = _shadow_ready_payload(
                record,
                content=content,
                summary=summary,
                topics=topics,
                sentences=indexed_sentences,
                study_items=study_items,
                vocabulary_coverage=vocabulary_coverage,
            )
            repository.validate_publication(user_id, _shadow_ready_record(record, payload))
            snapshot = tally.snapshot()
            usage = _durable_shadow_usage(tally, operation)
            usage["usage_complete"] = bool(not snapshot.missing_usage and snapshot.total_tokens > 0)
            meter.save_result(
                operation_id,
                {
                    "kind": "preload",
                    "state": "completed",
                    "usage": usage,
                    "response": payload,
                },
            )
            desired_outcome = "success"
        except Exception as exc:  # noqa: BLE001 - settle all durable outcomes
            provider_error = exc
            desired_outcome = (
                "failed_after_dispatch"
                if _dispatch_was_attempted(tally, exc)
                else "failed_before_dispatch"
            )
        finally:
            owns_publication = heartbeat.stop_and_verify()

        if provider_error is not None and _dispatch_was_attempted(tally, provider_error):
            try:
                partial_usage = _durable_shadow_usage(tally, operation)
                partial_usage["usage_complete"] = False
                meter.save_result(
                    operation_id,
                    {
                        "kind": "preload",
                        "state": "completed",
                        "usage": partial_usage,
                    },
                )
            except Exception:  # noqa: BLE001 - retain the already-persisted dispatch marker
                logger.warning(
                    "durable shadow partial evidence could not be saved operation_id=%s",
                    operation_id,
                )

        try:
            operation = _settle_durable_shadow(
                meter,
                operation_id,
                outcome=desired_outcome,
                result_ref=preload_id,
            )
        except Exception:  # noqa: BLE001 - retain a retryable pending record
            pending = dict(record)
            pending["status"] = (
                "ready_pending_usage" if desired_outcome == "success" else "failed_pending_usage"
            )
            pending["shadow_pending_outcome"] = desired_outcome
            pending["shadow_pending_result_ref"] = preload_id
            pending["content_retirement_pending"] = True
            pending.pop("_claimed_from_unstarted_processing", None)
            repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                pending,
                lease_id=lease_id,
            )
            logger.exception("durable shadow settlement failed operation_id=%s", operation_id)
            return

        if not owns_publication:
            return
        _finish_durable_shadow_publication(
            repository,
            content_store,
            meter,
            user_id,
            preload_id,
            learner_profile_fingerprint,
            record,
            operation,
            expected_status="running",
            lease_id=lease_id,
            admin_activity_repository=admin_activity_repository,
            tally=tally,
        )
        if provider_error:
            logger.warning(
                "durable shadow preload failed user=%s url=%s: %s",
                user_id,
                normalize_page_url(page_url),
                type(provider_error).__name__,
            )
    finally:
        meter.release_execution(operation_id, lease_id)


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

    if record.get("accounting_mode") == "shadow" and record.get("shadow_version") == 1:
        _run_durable_shadow_preload_job(
            repository,
            subscription_repository,
            usage_repository,
            content_store,
            user_id,
            page_url,
            preload_id,
            learner_profile_fingerprint,
            record,
            admin_activity_repository=admin_activity_repository,
            billing_provider_mode=billing_provider_mode,
        )
        return
    if isinstance(record.get("shadow_usage"), dict):
        _fail_unrecoverable_shadow_record(
            repository,
            content_store,
            user_id,
            preload_id,
            learner_profile_fingerprint,
            record,
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
        if operation.state == "released" and record.get("status") not in (
            "ready",
            "failed",
            "failed_pending_usage",
        ):
            recovery_lease_id = None
            expected_status = "processing"
            if record.get("status") == "running":
                recovery_now = datetime.now(UTC)
                if not _has_expired_preload_lease(record, recovery_now):
                    return
                recovery_lease_id = generate_uuid7()
                recovery_lease_expires_at = recovery_now + timedelta(
                    seconds=max(1, int(os.getenv("PRELOAD_WORKER_LEASE_SECONDS", "900")))
                )
                record = repository.claim_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    lease_id=recovery_lease_id,
                    now=recovery_now,
                    lease_expires_at=recovery_lease_expires_at,
                )
                if not record:
                    return
                record.pop("_claimed_from_unstarted_processing", None)
                expected_status = "running"
            if record.get("status") in ("processing", "running"):
                blocked = dict(record)
                blocked["status"] = "failed"
                blocked["content_retirement_pending"] = True
                blocked["usage_state"] = "released"
                blocked["error"] = (
                    "The usage reservation expired before analysis started. "
                    "Please submit the article again."
                )
                completed = repository.finish_processing(
                    user_id,
                    preload_id,
                    learner_profile_fingerprint,
                    blocked,
                    lease_id=recovery_lease_id,
                    expected_status=expected_status,
                )
                if completed:
                    _retire_terminal_content(
                        repository,
                        content_store,
                        user_id,
                        blocked,
                        learner_profile_fingerprint,
                    )
            return
        if operation and operation.state == "finalized":
            if record.get("status") in ("processing", "running"):
                interrupted = dict(record)
                interrupted["status"] = "failed"
                interrupted["content_retirement_pending"] = True
                interrupted["usage_state"] = (
                    "finalized"
                    if operation.dispatch_usage_completeness == "measured"
                    else "finalized_conservative"
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
                _retire_terminal_content(
                    repository,
                    content_store,
                    user_id,
                    interrupted,
                    learner_profile_fingerprint,
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
            if operation.dispatch_evidence_state in ("dispatched", "completed"):
                _finalize_dispatch_evidence(meter, operation, result_ref=preload_id)
            else:
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
            if record.get("failure_settlement") == "finalize_evidence":
                usage_state = _finalize_dispatch_evidence(
                    meter,
                    operation,
                    result_ref=preload_id,
                )
            elif record.get("failure_settlement") == "finalize_conservative":
                meter.finalize(
                    operation_id,
                    record.get("failure_usage")
                    or {"actual_cost_micro_usd": operation.reserved_cost_micro_usd},
                    result_ref=preload_id,
                    evidence_completeness="conservative",
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
    claimed_from_unstarted_processing = bool(
        record.pop("_claimed_from_unstarted_processing", False)
    )
    if reclaimed_worker_lease:
        _log_recovery_event(
            "execution_lease_recovered",
            operation_id=operation_id or preload_id,
            kind="preload",
        )
    if claimed_from_unstarted_processing and latest and latest.get("id") != preload_id:
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
        latest_operation = meter.get_operation(operation_id) or operation
        durable_result = meter.get_result(operation_id)
        if latest_operation.dispatch_evidence_state in ("dispatched", "completed"):
            try:
                usage_state = _finalize_dispatch_evidence(
                    meter,
                    latest_operation,
                    result_ref=preload_id,
                )
                interrupted = dict(record)
                interrupted["status"] = "failed"
                interrupted["content_retirement_pending"] = True
                interrupted["usage_state"] = usage_state
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
            if completed:
                _retire_terminal_content(
                    repository,
                    content_store,
                    user_id,
                    interrupted,
                    learner_profile_fingerprint,
                )
            return
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
                interrupted["content_retirement_pending"] = True
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
            if completed:
                _retire_terminal_content(
                    repository,
                    content_store,
                    user_id,
                    interrupted,
                    learner_profile_fingerprint,
                )
            return
        try:
            operation = meter.renew(operation_id, lease_expires_at)
        except UsageOperationStateError:
            blocked = dict(record)
            blocked["status"] = "failed"
            blocked["content_retirement_pending"] = True
            blocked["usage_state"] = "released"
            blocked["error"] = (
                "The usage reservation expired before analysis started. "
                "Please submit the article again."
            )
            completed = repository.finish_processing(
                user_id,
                preload_id,
                learner_profile_fingerprint,
                blocked,
                lease_id=lease_id,
            )
            meter.release_execution(operation_id, lease_id)
            if completed:
                _retire_terminal_content(
                    repository,
                    content_store,
                    user_id,
                    blocked,
                    learner_profile_fingerprint,
                )
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
                if provider_error is None:
                    snapshot = tally.snapshot()
                    durable_usage["usage_complete"] = bool(
                        not snapshot.missing_usage and snapshot.total_tokens > 0
                    )
                else:
                    # A dispatch-attempted provider error has no complete
                    # provider tally, even when its empty snapshot reports no
                    # missing fields. Preserve the reservation floor instead.
                    durable_usage["usage_complete"] = False
                meter.save_result(
                    operation_id,
                    {
                        "kind": "preload",
                        "state": "completed",
                        "usage": durable_usage,
                    },
                )
        except Exception as evidence_error:
            # The durable promotion may already have succeeded before the
            # TTL-private result write failed. Route through settlement so
            # exact safe evidence is not replaced by a reservation floor.
            if provider_error is None:
                provider_error = evidence_error
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
                latest_operation = meter.get_operation(operation_id) or operation
                if latest_operation.dispatch_evidence_state in ("dispatched", "completed"):
                    failed["failure_settlement"] = "finalize_evidence"
                else:
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
            if failed["failure_settlement"] == "finalize_evidence":
                failed["usage_state"] = _finalize_dispatch_evidence(
                    meter,
                    meter.get_operation(operation_id) or operation,
                    result_ref=preload_id,
                )
            elif failed["failure_settlement"] == "finalize_conservative":
                meter.finalize(
                    operation_id,
                    failed["failure_usage"],
                    result_ref=preload_id,
                    evidence_completeness="conservative",
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
            latest_operation = meter.get_operation(operation_id) or operation
            if latest_operation.dispatch_evidence_state in ("dispatched", "completed"):
                failed["failure_settlement"] = "finalize_evidence"
            else:
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
            if failed["failure_settlement"] == "finalize_evidence":
                _finalize_dispatch_evidence(
                    meter,
                    meter.get_operation(operation_id) or operation,
                    result_ref=preload_id,
                )
            else:
                meter.finalize(
                    operation_id,
                    failed["failure_usage"],
                    result_ref=preload_id,
                    evidence_completeness="conservative",
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
        latest_operation = meter.get_operation(operation_id) or operation
        if latest_operation.dispatch_evidence_state in ("dispatched", "completed"):
            _finalize_dispatch_evidence(
                meter,
                latest_operation,
                result_ref=preload_id,
            )
        else:
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
