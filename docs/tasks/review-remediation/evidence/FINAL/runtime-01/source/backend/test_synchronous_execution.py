"""The execution interface retains one claim and one dispatch attempt."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from accounts.storage import JsonSubscriptionRepository
from core.pipeline import PipelineError, UsageTally
from core.plans import PlanLimits
from core.usage_costs import ModelRate
from repositories.usage_repository import JsonUsageRepository
from schemas import ChatResponse
from services.synchronous_execution import SynchronousExecution
from services.usage_meter import UsageMeter


@pytest.fixture
def execution(tmp_path):
    meter = UsageMeter(
        JsonSubscriptionRepository(tmp_path / "subscriptions.json"),
        JsonUsageRepository(tmp_path / "usage.json"),
        "019b63f8-f600-7000-8000-000000000101",
        rate=ModelRate("test-model", 1, 1, "test-v1"),
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
        reservation_enabled=True,
    )
    operation = meter.reserve(
        "019b63f8-f600-7000-8000-000000000201",
        "payload",
        "chat",
        10,
    )
    return SynchronousExecution(meter, operation, kind="chat", response_model=ChatResponse)


def test_dispatch_requires_an_active_context(execution):
    provider = Mock(return_value="reply")
    with pytest.raises(RuntimeError, match="acquired claim"):
        execution.run(UsageTally(), provider, lambda reply: ChatResponse(reply=reply))
    with execution:
        pass
    with pytest.raises(RuntimeError, match="acquired claim"):
        execution.run(UsageTally(), provider, lambda reply: ChatResponse(reply=reply))
    provider.assert_not_called()


def test_a_caught_provider_failure_cannot_dispatch_again_in_the_same_claim(execution):
    error = PipelineError("provider unavailable", status_code=502)
    provider = Mock(side_effect=error)
    with execution:
        with pytest.raises(PipelineError) as failure:
            execution.run(UsageTally(), provider, lambda reply: ChatResponse(reply=reply))
        assert failure.value is error
        with pytest.raises(RuntimeError, match="only once"):
            execution.run(UsageTally(), provider, lambda reply: ChatResponse(reply=reply))
    assert provider.call_count == 1


def test_success_persists_a_result_and_replays_without_dispatch(execution):
    provider = Mock(return_value="reply")
    with execution:
        response = execution.run(
            UsageTally(rate=ModelRate("test-model", 1, 1, "test-v1")),
            provider,
            lambda reply: ChatResponse(reply=reply),
        )
        stored = execution.meter.get_result(execution.operation.operation_id)
        assert stored["response"] == response.model_dump()
        assert stored["state"] == "completed"
        with pytest.raises(RuntimeError, match="only once"):
            execution.run(UsageTally(), provider, lambda reply: ChatResponse(reply=reply))
    operation = execution.meter.get_operation(execution.operation.operation_id)
    assert operation.state == "finalized"
    with SynchronousExecution(
        execution.meter,
        operation,
        kind="chat",
        response_model=ChatResponse,
    ) as replay:
        assert replay.replay == response
        assert (
            replay.run(UsageTally(), provider, lambda value: ChatResponse(reply=value)) == response
        )
    assert provider.call_count == 1
