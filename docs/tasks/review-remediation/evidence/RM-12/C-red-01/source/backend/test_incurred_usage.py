"""Workflow regressions for usage retained after an incurred provider call."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
_HTML = (
    "<article><p>The first complete sentence provides enough article content for the "
    "preload worker to extract and analyze a realistic study unit.</p>"
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
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "0",
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
            rate=ModelRate(pipeline.OPENAI_MODEL, 1_000_000, 0, "incurred-usage-test"),
            reservation_enabled=not durable_shadow,
            durable_shadow=durable_shadow,
            provider_mode="mock",
        )

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
            *self.runner.calls[0][:4],
            billing_provider_mode="mock",
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

    def _assert_single_shadow_settlement(
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
        self.assertEqual(month["shadow_cost_micro_usd"], expected_cost)
        self.assertEqual(month["tokens"], expected_tokens)
        self.assertEqual(month["articles"], expected_articles)
        events = [
            item
            for item in read_json_list(self._usage_path)
            if item.get("record_type") == "usage_event"
            and item.get("operation_id") == operation_id
            and item.get("transition") == "shadow_settle"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actual_cost_micro_usd"], expected_cost)
        self.assertEqual(events[0]["tokens"], expected_tokens)

    def test_shadow_timeout_then_tool_fallback_retains_known_usage_once_after_ttl(
        self,
    ) -> None:
        meter = self._meter(durable_shadow=True)
        sentence = (
            "The first complete sentence provides enough article content for the preload worker."
        )
        client = _SequencedClient(
            [
                RuntimeError("timeout after dispatch"),
                _tool_response("get_coarse_sentence_split", {}, call_id="coarse"),
                _tool_response(
                    "submit_sentence_split",
                    {"sentences": [sentence]},
                    call_id="submit",
                ),
                _response(self._analysis_payload(), input_tokens=17),
            ]
        )
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
        self._assert_single_shadow_settlement(
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
        self._assert_single_shadow_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=1,
        )

    def test_shadow_complete_measured_cost_below_reservation_remains_exact(self) -> None:
        meter = self._meter(durable_shadow=True)
        sentence = (
            "The first complete sentence provides enough article content for the preload worker."
        )
        client = _SequencedClient(
            [
                _response({"sentences": [sentence]}, input_tokens=5),
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
        self._assert_single_shadow_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=5,
            expected_tokens=5,
            expected_articles=1,
        )

    def test_shadow_failed_preload_preserves_known_response_usage_without_article(self) -> None:
        meter = self._meter(durable_shadow=True)
        sentence = (
            "The first complete sentence provides enough article content for the preload worker."
        )
        client = _SequencedClient([_response({"sentences": [sentence]}, input_tokens=17)])
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
        self._assert_single_shadow_settlement(
            operation_id=_OPERATION_ID,
            expected_cost=17,
            expected_tokens=17,
            expected_articles=0,
        )

    def test_enforced_response_build_failure_retains_known_provider_usage_before_result_write(
        self,
    ) -> None:
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
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, 17)
        self.assertEqual(operation.tokens, 17)
        self.assertEqual(month["committed_cost_micro_usd"], 17)
        self.assertEqual(month["tokens"], 17)
        self.assertIsNone(self.usage.get_result(_USER_ID, request.operation_id))
        with mock.patch.object(
            reading,
            "_call_openai_json",
            side_effect=AssertionError("replay must not redispatch a provider"),
        ):
            with self.assertRaises(pipeline.PipelineError):
                reading.analyze_selection(self.preloads, _USER_ID, request, usage_meter=meter)


if __name__ == "__main__":
    unittest.main()
