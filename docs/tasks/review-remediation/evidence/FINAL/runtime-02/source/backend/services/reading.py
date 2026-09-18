"""Synchronous reading use cases and compatible handler entry points.

Preload commands and read-only projections are re-exported for existing callers.
Execution ownership and settlement are delegated to SynchronousExecution.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.ids import generate_uuid7
from core.pipeline import (
    UsageTally,
    _analysis_prompt,
    _build_chat_messages,
    _call_openai_chat,
    _call_openai_json,
    estimate_openai_call_cost_micro_usd,
)
from repositories.admin_activity import AdminActivityRepository
from repositories.page_preload_repository import (
    PagePreloadRepository,
)
from repositories.phrase_repository import PhraseRepository
from schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChatRequest,
    ChatResponse,
    PhraseCreateRequest,
    PhraseRecord,
)

from services.admin_activity import TerminalActivityOutcome, record_terminal_activity
from services.entitlements import EntitlementError, EntitlementGuard
from services.preloading import run_preload_job as run_preload_job
from services.preloading import submit_preload as submit_preload
from services.reading_queries import build_vocabulary_book as build_vocabulary_book
from services.reading_queries import get_preload_status as get_preload_status
from services.reading_queries import resolve_page_preload as _resolve_page_preload
from services.reading_support import (
    _dispatch_was_attempted,
    _shadow_estimate,
    _shadow_usage,
    canonical_payload_hash,
)
from services.synchronous_execution import SynchronousExecution
from services.usage_meter import UsageMeter


def analyze_selection(
    repository: PagePreloadRepository,
    user_id: str,
    request: AnalyzeRequest,
    guard: EntitlementGuard | None = None,
    usage_meter: UsageMeter | None = None,
) -> AnalyzeResponse:
    preload = _resolve_page_preload(
        repository,
        user_id=user_id,
        preload_id=request.page_preload_id,
        page_url=request.page_url,
    )

    if preload:
        normalized_selection = " ".join(request.text.split())
        for sentence in preload.get("sentences") or []:
            sentence_text = " ".join(sentence.get("text", "").split())
            if sentence_text == normalized_selection or normalized_selection in sentence_text:
                analysis = sentence.get("analysis") or {}
                return AnalyzeResponse(
                    original_text=request.text,
                    used_preload=True,
                    **analysis,
                )

    # Cache miss: this path calls OpenAI, so it counts against the monthly
    # token budget (selection analyses are not article/chat metered).
    reservation_enabled = bool(usage_meter and usage_meter.reservation_enabled)
    if guard and not reservation_enabled:
        guard.check_tokens()
    prompt = _analysis_prompt(request, preload)
    shadow_meter = usage_meter if usage_meter and not reservation_enabled else None
    shadow_estimated_cost = (
        _shadow_estimate(
            lambda: estimate_openai_call_cost_micro_usd(
                [{"role": "user", "content": prompt}], max_output_tokens=1000
            )
        )
        if shadow_meter
        else 0
    )
    if reservation_enabled:
        operation = usage_meter.reserve(
            request.operation_id,
            canonical_payload_hash(request, exclude={"operation_id"}),
            "cost",
            estimate_openai_call_cost_micro_usd(
                [{"role": "user", "content": prompt}],
                max_output_tokens=1000,
            ),
        )
        with SynchronousExecution(
            usage_meter,
            operation,
            kind="analyze",
            response_model=AnalyzeResponse,
        ) as execution:
            if execution.replay is not None:
                return execution.replay
            tally = UsageTally()
            return execution.run(
                tally,
                lambda: _call_openai_json(prompt, max_completion_tokens=1000, tally=tally),
                lambda parsed: AnalyzeResponse(
                    original_text=request.text,
                    used_preload=preload is not None,
                    **parsed,
                ),
            )

    tally = (
        UsageTally(rate=shadow_meter.rate if shadow_meter else None)
        if guard or shadow_meter
        else None
    )
    provider_error = None
    try:
        parsed = _call_openai_json(prompt, max_completion_tokens=1000, tally=tally)
    except Exception as error:
        provider_error = error
    if provider_error is not None:
        if shadow_meter:
            shadow_meter.observe_shadow(
                request.operation_id,
                "cost",
                shadow_estimated_cost,
                _shadow_usage(tally),
                outcome="conservative_failure"
                if _dispatch_was_attempted(tally, provider_error)
                else "failed_before_dispatch",
            )
        raise provider_error
    try:
        response = AnalyzeResponse(
            original_text=request.text,
            used_preload=preload is not None,
            **parsed,
        )
        if guard:
            guard.record_tokens(tally.total_tokens if tally else 0)
        if shadow_meter:
            shadow_meter.observe_shadow(
                request.operation_id,
                "cost",
                shadow_estimated_cost,
                _shadow_usage(tally),
                outcome="succeeded",
            )
    except Exception as error:
        if shadow_meter:
            shadow_meter.observe_shadow(
                request.operation_id,
                "cost",
                shadow_estimated_cost,
                _shadow_usage(tally),
                outcome="conservative_failure"
                if _dispatch_was_attempted(tally, error)
                else "failed_before_dispatch",
            )
        raise
    return response


def chat_reply(
    repository: PagePreloadRepository,
    user_id: str,
    request: ChatRequest,
    guard: EntitlementGuard | None = None,
    usage_meter: UsageMeter | None = None,
    admin_activity_repository: AdminActivityRepository | None = None,
) -> ChatResponse:
    reservation_enabled = bool(usage_meter and usage_meter.reservation_enabled)
    if guard and not reservation_enabled:
        try:
            guard.check_chat()
        except EntitlementError as exc:
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome(
                    operation_id=request.operation_id,
                    user_id=user_id,
                    operation="chat",
                    status="quota_blocked",
                    error=exc,
                    model=usage_meter.rate.model if usage_meter else None,
                ),
                preserve_failure=True,
            )
            raise

    preload = _resolve_page_preload(
        repository,
        user_id=user_id,
        preload_id=request.page_preload_id,
        page_url=request.page_url,
    )
    messages = _build_chat_messages(request, preload)
    shadow_meter = usage_meter if usage_meter and not reservation_enabled else None
    shadow_estimated_cost = (
        _shadow_estimate(
            lambda: estimate_openai_call_cost_micro_usd(messages, max_output_tokens=900)
        )
        if shadow_meter
        else 0
    )
    if reservation_enabled:
        try:
            operation = usage_meter.reserve(
                request.operation_id,
                canonical_payload_hash(request, exclude={"operation_id"}),
                "chat",
                estimate_openai_call_cost_micro_usd(messages, max_output_tokens=900),
            )
        except EntitlementError as exc:
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome(
                    operation_id=request.operation_id,
                    user_id=user_id,
                    operation="chat",
                    status="quota_blocked",
                    error=exc,
                    model=usage_meter.rate.model,
                ),
                preserve_failure=True,
            )
            raise
        with SynchronousExecution(
            usage_meter,
            operation,
            kind="chat",
            response_model=ChatResponse,
        ) as execution:
            if execution.replay is not None:
                record_terminal_activity(
                    admin_activity_repository,
                    TerminalActivityOutcome(
                        operation_id=request.operation_id,
                        user_id=user_id,
                        operation="chat",
                        status="success",
                        model=operation.model,
                        usage={"actual_cost_micro_usd": operation.actual_cost_micro_usd},
                    ),
                )
                return execution.replay
            tally = UsageTally()

            def record_execution_failure(error: Exception) -> None:
                record_terminal_activity(
                    admin_activity_repository,
                    TerminalActivityOutcome(
                        operation_id=request.operation_id,
                        user_id=user_id,
                        operation="chat",
                        status="failed",
                        error=error,
                        tally=tally,
                        model=operation.model,
                    ),
                    preserve_failure=True,
                )

            response = execution.run(
                tally,
                lambda: _call_openai_chat(messages, max_completion_tokens=900, tally=tally),
                lambda reply: ChatResponse(reply=reply),
                on_failure=record_execution_failure,
            )
            record_terminal_activity(
                admin_activity_repository,
                TerminalActivityOutcome(
                    operation_id=request.operation_id,
                    user_id=user_id,
                    operation="chat",
                    status="success",
                    tally=tally,
                    usage=execution.usage,
                    model=operation.model,
                ),
            )
            return response

    tally = (
        UsageTally(rate=shadow_meter.rate if shadow_meter else None)
        if guard or shadow_meter
        else None
    )

    def record_legacy_failure(error: Exception) -> None:
        record_terminal_activity(
            admin_activity_repository,
            TerminalActivityOutcome(
                operation_id=request.operation_id,
                user_id=user_id,
                operation="chat",
                status="failed",
                error=error,
                tally=tally,
                model=shadow_meter.rate.model if shadow_meter else None,
            ),
            preserve_failure=True,
        )
        if shadow_meter:
            shadow_meter.observe_shadow(
                request.operation_id,
                "chat",
                shadow_estimated_cost,
                _shadow_usage(tally),
                outcome="conservative_failure"
                if _dispatch_was_attempted(tally, error)
                else "failed_before_dispatch",
            )

    provider_error = None
    try:
        reply = _call_openai_chat(messages, max_completion_tokens=900, tally=tally)
    except Exception as error:
        provider_error = error
    if provider_error is not None:
        record_legacy_failure(provider_error)
        raise provider_error
    try:
        response = ChatResponse(reply=reply)
        if guard:
            guard.record_chat(tokens=tally.total_tokens if tally else 0)
        if shadow_meter:
            shadow_meter.observe_shadow(
                request.operation_id,
                "chat",
                shadow_estimated_cost,
                _shadow_usage(tally),
                outcome="succeeded",
            )
    except Exception as error:
        record_legacy_failure(error)
        raise
    record_terminal_activity(
        admin_activity_repository,
        TerminalActivityOutcome(
            operation_id=request.operation_id,
            user_id=user_id,
            operation="chat",
            status="success",
            tally=tally,
            model=shadow_meter.rate.model if shadow_meter else None,
        ),
    )
    return response


def list_phrases(repository: PhraseRepository, user_id: str) -> list[PhraseRecord]:
    return [PhraseRecord(**phrase) for phrase in repository.list_for_user(user_id)]


def create_phrase(
    repository: PhraseRepository, user_id: str, request: PhraseCreateRequest
) -> PhraseRecord:
    record = PhraseRecord(
        id=generate_uuid7(),
        created_at=datetime.now(UTC).isoformat(),
        **request.model_dump(),
    )
    repository.create(user_id, record.model_dump())
    return record
