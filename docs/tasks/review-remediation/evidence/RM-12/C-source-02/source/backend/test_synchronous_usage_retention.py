"""Synchronous retries retain durable accounting evidence without redispatching."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from accounts.storage import JsonSubscriptionRepository
from core.pipeline import UsageTally
from core.plans import PlanLimits
from core.usage_costs import ModelRate
from repositories.usage_repository import JsonUsageRepository
from schemas import ChatResponse
from services.synchronous_execution import SynchronousExecution
from services.usage_meter import UsageMeter


def _meter(tmp_path) -> UsageMeter:
    return UsageMeter(
        JsonSubscriptionRepository(tmp_path / "subscriptions.json"),
        JsonUsageRepository(tmp_path / "usage.json"),
        "019b63f8-f600-7000-8000-000000000111",
        rate=ModelRate("test-model", 1_000_000, 1_000_000, "test-v1"),
        now=datetime.now(UTC),
        plan_loader=lambda _: PlanLimits(
            "pro",
            articles_per_month=10,
            chats_per_month=10,
            tokens_per_month=100_000,
            sentences_per_article=50,
            cost_micro_usd_per_month=100_000,
            source_tokens_per_article=12_000,
        ),
    )


def test_retry_preserves_full_result_after_finalization_failure_without_redispatch(tmp_path):
    meter = _meter(tmp_path)
    operation = meter.reserve(
        "019b63f8-f600-7000-8000-000000000211",
        "payload",
        "chat",
        13,
    )
    tally = UsageTally(rate=meter.rate)

    def provider() -> str:
        tally.mark_dispatch_attempt()
        tally.add_response(
            SimpleNamespace(
                model="test-model",
                usage=SimpleNamespace(input_tokens=17, output_tokens=0, total_tokens=17),
            )
        )
        return "reply"

    execution = SynchronousExecution(
        meter,
        operation,
        kind="chat",
        response_model=ChatResponse,
    )
    with patch.object(meter, "finalize", side_effect=RuntimeError("finalize unavailable")):
        with execution, pytest.raises(RuntimeError, match="finalize unavailable"):
            execution.run(tally, provider, lambda reply: ChatResponse(reply=reply))

    stored = meter.get_result(operation.operation_id)
    assert stored is not None
    assert stored["response"] == {"reply": "reply"}
    assert meter.get_operation(operation.operation_id).state == "reserved"

    blocked_provider = Mock(side_effect=AssertionError("retry must not redispatch"))
    with SynchronousExecution(
        meter,
        meter.get_operation(operation.operation_id),
        kind="chat",
        response_model=ChatResponse,
    ) as retry:
        assert retry.run(UsageTally(rate=meter.rate), blocked_provider, ChatResponse) == ChatResponse(
            reply="reply"
        )

    blocked_provider.assert_not_called()
    finalized = meter.get_operation(operation.operation_id)
    month = meter.usage_repository.get_month(finalized.user_id, finalized.month)
    assert (finalized.state, finalized.actual_cost_micro_usd, finalized.tokens) == (
        "finalized",
        17,
        17,
    )
    assert (month["committed_cost_micro_usd"], month["tokens"]) == (17, 17)
