"""Workflow regressions for usage retained after an incurred provider call."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import core.pipeline as pipeline
from accounts.storage import JsonSubscriptionRepository
from core.usage_costs import ModelRate
from pydantic import ValidationError
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import AnalyzeRequest, PagePreloadRequest
from services import preloading, reading
from services.usage_meter import UsageMeter
from storage.json_list_store import read_json_list, write_json_list
from storage.preload_content_store import FilesystemPreloadContentStore

_USER_ID = "incurred-usage-user"
_OPERATION_ID = "019b63f8-f600-7000-8000-000000000901"
_PAGE_URL = "https://example.com/incurred-usage"
_ARTICLE_SENTENCE = (
    "The first complete sentence provides enough article content for the preload worker "
    "to extract and analyze a realistic study unit."
)
_HTML = (
    f"<article><p>{_ARTICLE_SENTENCE}</p>"
    "<p>The second complete sentence keeps the fixture above the synchronous "
    "extraction threshold without relying on a private provider response.</p></article>"
)


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue(
        self,
        user_id: str,
        page_url: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        usage_context: dict | None = None,
    ) -> None:
        self.calls.append(
            (user_id, page_url, preload_id, learner_profile_fingerprint, usage_context)
        )


class _SequencedClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create),
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("The provider stub received an unexpected extra call.")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FailFirstCompletedResultRepository(JsonUsageRepository):
    """Simulate a completed private-result write failing before promotion."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.completed_write_failures = 0

    def save_result(
        self,
        user_id: str,
        operation_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if self.completed_write_failures == 0 and result.get("state") == "completed":
            self.completed_write_failures += 1
            raise OSError("completed evidence write failed before promotion")
        return super().save_result(user_id, operation_id, result)


class _FailCompletedPromotionRepository(JsonUsageRepository):
    """Keep completed evidence retryable while permitting the dispatch marker."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.reject_completed_promotions = True
        self.completed_write_attempts = 0

    def save_result(
        self,
        user_id: str,
        operation_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if self.reject_completed_promotions and result.get("state") == "completed":
            self.completed_write_attempts += 1
            raise OSError("completed evidence promotion remains unavailable")
        return super().save_result(user_id, operation_id, result)


def _response(payload: dict, *, input_tokens: int, output_tokens: int = 0) -> object:
    return types.SimpleNamespace(
        model=pipeline.OPENAI_MODEL,
        usage=types.SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(content=json.dumps(payload), tool_calls=None),
            )
        ],
    )


def _tool_response(name: str, arguments: dict, *, call_id: str) -> object:
    return types.SimpleNamespace(
        model=pipeline.OPENAI_MODEL,
        usage=types.SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0),
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content=None,
                    tool_calls=[
                        types.SimpleNamespace(
                            id=call_id,
                            type="function",
                            function=types.SimpleNamespace(
                                name=name,
                                arguments=json.dumps(arguments),
                            ),
                        )
                    ],
                )
            )
        ],
    )


class IncurredUsageWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(self._temporary_directory.name)
        self.preloads = JsonPagePreloadRepository(directory / "preloads.json")
        self.usage = JsonUsageRepository(directory / "usage.json")
        self.subscriptions = JsonSubscriptionRepository(directory / "subscriptions.json")
        self.content = FilesystemPreloadContentStore(directory / "content")
        self.runner = _RecordingRunner()
        self._usage_path = directory / "usage.json"
        self._rate_environment = mock.patch.dict(
            os.environ,
            {
                "OPENAI_MODEL": pipeline.OPENAI_MODEL,
                "OPENAI_RATE_CARD_VERSION": "incurred-usage-test",
                "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1000000",
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1000000",
            },
        )
        self._rate_environment.start()

    def tearDown(self) -> None:
        self._rate_environment.stop()
        self._temporary_directory.cleanup()

    def _meter(self, *, durable_shadow: bool) -> UsageMeter:
        return UsageMeter(
            self.subscriptions,
            self.usage,
            _USER_ID,
            rate=ModelRate(
                pipeline.OPENAI_MODEL,
                1_000_000,
                1_000_000,
                "incurred-usage-test",
            ),
            reservation_enabled=not durable_shadow,
            durable_shadow=durable_shadow,
            provider_mode="mock",
        )

    def _fail_first_completed_write(self) -> _FailFirstCompletedResultRepository:
        failing_repository = _FailFirstCompletedResultRepository(self._usage_path)
        self.usage = failing_repository
        return failing_repository

    def _fail_completed_promotions(self) -> _FailCompletedPromotionRepository:
        failing_repository = _FailCompletedPromotionRepository(self._usage_path)
        self.usage = failing_repository
        return failing_repository

    @staticmethod
    def _request(operation_id: str = _OPERATION_ID) -> PagePreloadRequest:
        return PagePreloadRequest(
            operation_id=operation_id,
            page_url=_PAGE_URL,
            page_title="Incurred usage article",
            html=_HTML,
        )

    def _submit(self, meter: UsageMeter) -> None:
        preloading.submit_preload(
            self.preloads,
            self.runner,
            self.content,
            _USER_ID,
            self._request(),
            usage_meter=meter,
        )

    def _run_worker(self) -> None:
        preloading.run_preload_job(
            self.preloads,
            self.subscriptions,
            self.usage,
            self.content,
            *self.runner.calls[0],
            billing_provider_mode="mock",
        )

    @staticmethod
    def _fallback_client(*, analysis_input_tokens: int) -> _SequencedClient:
        return _SequencedClient(
            [
                RuntimeError("timeout after dispatch"),
                _tool_response("get_coarse_sentence_split", {}, call_id="coarse"),
                _tool_response(
                    "submit_sentence_split",
                    {"sentences": [_ARTICLE_SENTENCE]},
                    call_id="submit",
                ),
                _response(
                    IncurredUsageWorkflowTests._analysis_payload(),
                    input_tokens=analysis_input_tokens,
                ),
            ]
        )

    @staticmethod
    def _analysis_payload() -> dict:
        return {
            "summary": "A durable summary.",
            "topics": ["usage"],
            "sentences": [
                {
                    "index": 0,
                    "translation": "A translation.",
                    "grammar": "A grammar note.",
                    "nuance": "",
                    "vocabulary": [],
                    "examples": [],
                    "study_tip": "",
                }
            ],
        }

    def _assert_single_settlement(
        self,
        *,
        operation_id: str,
        expected_cost: int,
        expected_tokens: int,
        expected_articles: int,
    ) -> None:
        operation = self.usage.get_operation(_USER_ID, operation_id)
        self.assertIsNotNone(operation)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, expected_cost)
        self.assertEqual(operation.tokens, expected_tokens)
        if operation.accounting_mode == "shadow":
            cost_field = "shadow_cost_micro_usd"
            transition = "shadow_settle"
        else:
            cost_field = "committed_cost_micro_usd"
            transition = "finalize"
        self.assertEqual(month[cost_field], expected_cost)
        self.assertEqual(month["tokens"], expected_tokens)
        self.assertEqual(month["articles"], expected_articles)
        events = [
            item
            for item in read_json_list(self._usage_path)
            if item.get("record_type") == "usage_event"
            and item.get("operation_id") == operation_id
            and item.get("transition") == transition
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actual_cost_micro_usd"], expected_cost)
        self.assertEqual(events[0]["tokens"], expected_tokens)

    def test_shadow_timeout_then_tool_fallback_retains_known_usage_once_after_ttl(
        self,
    ) -> None:
        meter = self._meter(durable_shadow=True)
        client = self._fallback_client(analysis_input_tokens=17)
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
        ):
            self._submit(meter)
            self._run_worker()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.shadow_outcome, "success")
        self.assertEqual(operation.dispatch_usage_completeness, "conservative")
        self.assertEqual(operation.dispatch_usage["input_tokens"], 17)
        self.assertEqual(operation.dispatch_usage["actual_cost_micro_usd"], 17)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(record["status"], "ready")
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=1,
        )
        self.assertEqual(len(client.calls), 4)

        records = read_json_list(self._usage_path)
        for record in records:
            if record.get("record_type") == "usage_result":
                record["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        write_json_list(self._usage_path, records)
        self.assertIsNone(self.usage.get_result(_USER_ID, _OPERATION_ID))
        with mock.patch.object(
            pipeline,
            "_client",
            side_effect=AssertionError("TTL replay must not redispatch a provider"),
        ):
            self._run_worker()
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=1,
        )

    def test_shadow_timeout_below_reservation_keeps_one_conservative_floor(self) -> None:
        meter = self._meter(durable_shadow=True)
        client = self._fallback_client(analysis_input_tokens=5)
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
        ):
            self._submit(meter)
            self._run_worker()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.dispatch_usage_completeness, "conservative")
        self.assertEqual(operation.dispatch_usage["input_tokens"], 5)
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=13,
            expected_tokens=5,
            expected_articles=1,
        )
        self.assertEqual(len(client.calls), 4)

    def test_shadow_complete_measured_cost_below_reservation_remains_exact(self) -> None:
        meter = self._meter(durable_shadow=True)
        client = _SequencedClient(
            [
                _response({"sentences": [_ARTICLE_SENTENCE]}, input_tokens=5),
                _response(self._analysis_payload(), input_tokens=0),
            ]
        )
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
        ):
            self._submit(meter)
            self._run_worker()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.dispatch_usage_completeness, "measured")
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(record["status"], "ready")
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=5,
            expected_tokens=5,
            expected_articles=1,
        )
        self.assertEqual(len(client.calls), 2)

    def test_shadow_canonical_numeric_promotion_survives_expiry_before_worker_retry(
        self,
    ) -> None:
        failed_promotions = self._fail_completed_promotions()
        meter = self._meter(durable_shadow=True)
        client = _SequencedClient(
            [
                _response({"sentences": [_ARTICLE_SENTENCE]}, input_tokens=17),
                _response(self._analysis_payload(), input_tokens=0),
            ]
        )
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(
                UsageMeter,
                "prepare_shadow_settlement",
                side_effect=OSError("delay shadow settlement after numeric promotion"),
            ),
        ):
            self._submit(meter)
            self._run_worker()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        pending = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertGreaterEqual(failed_promotions.completed_write_attempts, 2)
        self.assertEqual(operation.state, "reserved")
        self.assertIsNone(operation.shadow_pending_outcome)
        self.assertEqual(operation.dispatch_evidence_state, "completed")
        self.assertEqual(operation.dispatch_usage_completeness, "measured")
        self.assertEqual(
            operation.dispatch_usage,
            {
                "actual_cost_micro_usd": 17,
                "input_tokens": 17,
                "output_tokens": 0,
                "total_tokens": 17,
            },
        )
        self.assertEqual(operation.actual_cost_micro_usd, 0)
        self.assertEqual(month["shadow_cost_micro_usd"], 0)
        self.assertEqual(month["tokens"], 0)
        self.assertEqual(month["articles"], 0)
        self.assertEqual(pending["status"], "failed_pending_usage")
        self.assertEqual(pending["shadow_pending_outcome"], "failed_after_dispatch")
        self.assertNotIn("shadow_evidence_retry_usage", pending)
        self.assertEqual(len(client.calls), 2)

        self.assertEqual(
            self.usage.reclaim_expired(
                _USER_ID,
                datetime.now(UTC) + timedelta(days=1),
            ),
            1,
        )
        with mock.patch.object(
            pipeline,
            "_client",
            side_effect=AssertionError("reclaim recovery must not redispatch"),
        ):
            self._run_worker()

        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(record["status"], "failed")
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=0,
        )

    def test_shadow_failed_preload_preserves_known_response_usage_without_article(self) -> None:
        failed_write = self._fail_first_completed_write()
        meter = self._meter(durable_shadow=True)
        client = _SequencedClient([_response({"sentences": [_ARTICLE_SENTENCE]}, input_tokens=17)])
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                side_effect=RuntimeError("analysis construction failed"),
            ),
        ):
            self._submit(meter)
            self._run_worker()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.shadow_outcome, "failed_after_dispatch")
        self.assertEqual(failed_write.completed_write_failures, 1)
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=0,
        )
        with mock.patch.object(
            pipeline,
            "_client",
            side_effect=AssertionError("replay must not redispatch after an incurred failure"),
        ):
            self._run_worker()
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=0,
        )

    def test_enforced_timeout_then_tool_fallback_retains_incurred_usage_once(self) -> None:
        meter = self._meter(durable_shadow=False)
        client = self._fallback_client(analysis_input_tokens=17)
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
        ):
            self._submit(meter)
            self._run_worker()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(record["status"], "ready")
        self.assertEqual(operation.dispatch_usage_completeness, "conservative")
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=1,
        )
        self.assertEqual(len(client.calls), 4)

    def test_enforced_failed_preload_keeps_known_response_usage_and_reserved_article(self) -> None:
        failed_write = self._fail_first_completed_write()
        meter = self._meter(durable_shadow=False)
        client = _SequencedClient([_response({"sentences": [_ARTICLE_SENTENCE]}, input_tokens=17)])
        with (
            mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13),
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                side_effect=RuntimeError("analysis construction failed"),
            ),
        ):
            self._submit(meter)
            self._run_worker()

        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(failed_write.completed_write_failures, 1)
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=1,
        )
        with mock.patch.object(
            pipeline,
            "_client",
            side_effect=AssertionError("replay must not redispatch after an incurred failure"),
        ):
            self._run_worker()
        self._assert_single_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=1,
        )

    def test_enforced_response_build_failure_retains_known_provider_usage_before_result_write(
        self,
    ) -> None:
        failed_write = self._fail_first_completed_write()
        meter = self._meter(durable_shadow=False)
        request = AnalyzeRequest(
            operation_id="019b63f8-f600-7000-8000-000000000902",
            text="A selection whose response model rejects the provider payload.",
        )

        def invalid_provider(*_args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(
                        input_tokens=17,
                        output_tokens=0,
                        total_tokens=17,
                    ),
                )
            )
            return {"translation": ["not a string"]}

        with (
            mock.patch.object(reading, "estimate_openai_call_cost_micro_usd", return_value=13),
            mock.patch.object(reading, "_call_openai_json", side_effect=invalid_provider),
            self.assertRaises(ValidationError),
        ):
            reading.analyze_selection(self.preloads, _USER_ID, request, usage_meter=meter)

        operation = self.usage.get_operation(_USER_ID, request.operation_id)
        self.assertEqual(failed_write.completed_write_failures, 1)
        self._assert_single_settlement(
            operation_id=request.operation_id,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=0,
        )
        stored = self.usage.get_result(_USER_ID, request.operation_id)
        if stored is not None:
            self.assertNotIn("response", stored)
            self.assertNotIn(request.text, json.dumps(stored, sort_keys=True))
        with mock.patch.object(
            reading,
            "_call_openai_json",
            side_effect=AssertionError("replay must not redispatch a provider"),
        ):
            with self.assertRaises(pipeline.PipelineError):
                reading.analyze_selection(self.preloads, _USER_ID, request, usage_meter=meter)


if __name__ == "__main__":
    unittest.main()
