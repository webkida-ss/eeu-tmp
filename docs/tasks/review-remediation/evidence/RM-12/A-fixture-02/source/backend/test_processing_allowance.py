"""Public regressions for one effective monthly processing allowance."""

from __future__ import annotations

import os
import tempfile
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import core.pipeline as pipeline
from accounts.storage import JsonSubscriptionRepository
from core.plans import get_plan_limits
from core.usage_costs import ModelRate
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import PagePreloadRequest
from services import preloading
from services.entitlements import (
    EffectiveProcessingAllowance,
    build_guard,
    usage_summary,
)
from services.usage_meter import UsageMeter
from storage.preload_content_store import FilesystemPreloadContentStore

_JULY = datetime(2026, 7, 31, 23, 50, tzinfo=UTC)
_AUGUST = datetime(2026, 8, 1, 0, 10, tzinfo=UTC)
_USER_ID = "processing-allowance-user"
_SECOND_USER_ID = "processing-allowance-other-user"
_PRO_OPERATION_ID = "019b63f8-f600-7000-8000-000000000701"
_CURRENT_OPERATION_ID = "019b63f8-f600-7000-8000-000000000702"
_SOURCE_OPERATION_ID = "019b63f8-f600-7000-8000-000000000703"
_UPGRADE_OPERATION_ID = "019b63f8-f600-7000-8000-000000000704"
_SHADOW_OPERATION_ID = "019b63f8-f600-7000-8000-000000000705"
_SHADOW_CURRENT_OPERATION_ID = "019b63f8-f600-7000-8000-000000000706"


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


class ProcessingAllowanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(self._temporary_directory.name)
        self.preloads = JsonPagePreloadRepository(directory / "preloads.json")
        self.usage = JsonUsageRepository(directory / "usage.json")
        self.subscriptions = JsonSubscriptionRepository(directory / "subscriptions.json")
        self.content = FilesystemPreloadContentStore(directory / "content")
        self.runner = _RecordingRunner()
        self._rate_environment = mock.patch.dict(
            os.environ,
            {
                "OPENAI_MODEL": pipeline.OPENAI_MODEL,
                "OPENAI_RATE_CARD_VERSION": "allowance-test",
                "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
            },
        )
        self._rate_environment.start()
        self.basic = get_plan_limits("basic")
        self.pro = get_plan_limits("pro")
        self.rate = ModelRate(pipeline.OPENAI_MODEL, 1, 1, "allowance-test")

    def tearDown(self) -> None:
        self._rate_environment.stop()
        self._temporary_directory.cleanup()

    @staticmethod
    def _html(sentence_count: int, *, words_per_sentence: int = 20) -> str:
        sentence = " ".join(["reading"] * words_per_sentence)
        paragraphs = [f"<p>Sentence {index} {sentence}.</p>" for index in range(sentence_count)]
        return "<article>" + "".join(paragraphs) + "</article>"

    @staticmethod
    def _subscription(plan: str) -> dict:
        return {
            "plan": plan,
            "status": "active",
            "current_period_end": int(datetime(2026, 12, 1, tzinfo=UTC).timestamp()),
            "entitlement_provider": "mock",
        }

    def _meter(
        self,
        user_id: str,
        now: datetime,
        *,
        durable_shadow: bool = False,
    ) -> UsageMeter:
        return UsageMeter(
            self.subscriptions,
            self.usage,
            user_id,
            rate=self.rate,
            now=now,
            provider_mode="mock",
            reservation_enabled=not durable_shadow,
            durable_shadow=durable_shadow,
        )

    def _guard(self, user_id: str, now: datetime):
        return build_guard(
            self.subscriptions,
            self.usage,
            user_id,
            now,
            provider_mode="mock",
        )

    def _request(self, operation_id: str, *, page_url: str, html: str) -> PagePreloadRequest:
        return PagePreloadRequest(
            operation_id=operation_id,
            page_url=page_url,
            page_title="Allowance article",
            html=html,
        )

    def _submit(
        self,
        user_id: str,
        request: PagePreloadRequest,
        meter: UsageMeter,
    ):
        return preloading.submit_preload(
            self.preloads,
            self.runner,
            self.content,
            user_id,
            request,
            self._guard(user_id, meter.now),
            usage_meter=meter,
        )

    def _run_worker(self, call: tuple) -> None:
        def analyze(sentences, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            return (
                "summary",
                [],
                [
                    {
                        "id": f"analysis-{index}",
                        "index": index,
                        "text": sentence,
                        "analysis": {},
                    }
                    for index, sentence in enumerate(sentences)
                ],
            )

        with (
            mock.patch.object(
                pipeline,
                "_split_sentences_with_ai",
                side_effect=RuntimeError("provider splitter unavailable"),
            ),
            mock.patch.object(preloading, "_analyze_sentences", side_effect=analyze),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            preloading.run_preload_job(
                self.preloads,
                self.subscriptions,
                self.usage,
                self.content,
                *call[:4],
                billing_provider_mode="mock",
            )

    def test_same_month_pro_allowance_survives_downgrade_across_submit_estimate_worker_and_summary(
        self,
    ) -> None:
        self.subscriptions.upsert(_USER_ID, self._subscription("pro"))
        pro_request = self._request(
            _PRO_OPERATION_ID,
            page_url="https://example.com/pro-seed",
            html=self._html(self.basic.sentences_per_article + 30, words_per_sentence=180),
        )
        self._submit(_USER_ID, pro_request, self._meter(_USER_ID, _JULY))

        self.subscriptions.upsert(_USER_ID, {"plan": "basic", "status": "canceled"})
        current_meter = self._meter(_USER_ID, _JULY)
        allowance = current_meter.processing_allowance()
        self.assertIsInstance(allowance, EffectiveProcessingAllowance)
        self.assertEqual(allowance.month, "2026-07")
        self.assertEqual(allowance.sentences_per_article, self.pro.sentences_per_article)
        self.assertEqual(allowance.source_tokens_per_article, self.pro.source_tokens_per_article)

        estimates: list[tuple[int | None, int | None]] = []
        original_estimate = preloading.estimate_article_cost_micro_usd

        def estimate(prepared, **kwargs):
            estimates.append((prepared.sentence_limit, prepared.source_token_limit))
            return original_estimate(prepared, **kwargs)

        current_request = self._request(
            _CURRENT_OPERATION_ID,
            page_url="https://example.com/current-month",
            html=self._html(self.basic.sentences_per_article + 30, words_per_sentence=180),
        )
        with mock.patch.object(preloading, "estimate_article_cost_micro_usd", side_effect=estimate):
            response = self._submit(_USER_ID, current_request, current_meter)

        record = self.preloads.get_by_id(_USER_ID, _CURRENT_OPERATION_ID)
        operation = self.usage.get_operation(_USER_ID, _CURRENT_OPERATION_ID)
        context = self.runner.calls[1][4]
        summary = usage_summary(self._guard(_USER_ID, _JULY))
        self.assertEqual(response.preload.sentence_limit, self.pro.sentences_per_article)
        self.assertEqual(response.preload.source_token_limit, self.pro.source_tokens_per_article)
        self.assertEqual(
            estimates, [(self.pro.sentences_per_article, self.pro.source_tokens_per_article)]
        )
        self.assertEqual(record["sentence_limit"], self.pro.sentences_per_article)
        self.assertEqual(record["source_token_limit"], self.pro.source_tokens_per_article)
        self.assertEqual(operation.sentences_per_article, self.pro.sentences_per_article)
        self.assertEqual(operation.source_tokens_per_article, self.pro.source_tokens_per_article)
        self.assertEqual(context["sentence_limit"], self.pro.sentences_per_article)
        self.assertEqual(context["source_token_limit"], self.pro.source_tokens_per_article)
        self.assertEqual(summary["sentences_per_article"], self.pro.sentences_per_article)
        self.assertEqual(summary["source_tokens_per_article"], self.pro.source_tokens_per_article)

        self._run_worker(self.runner.calls[1])
        ready = self.preloads.get_by_id(_USER_ID, _CURRENT_OPERATION_ID)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(len(ready["sentences"]), self.basic.sentences_per_article + 30)
        self.assertGreater(ready["source_tokens_analyzed"], self.basic.source_tokens_per_article)
        self.assertLessEqual(ready["source_tokens_analyzed"], self.pro.source_tokens_per_article)

    def test_source_token_boundary_uses_the_same_retained_pro_allowance(self) -> None:
        self.subscriptions.upsert(_USER_ID, self._subscription("pro"))
        self._submit(
            _USER_ID,
            self._request(
                _PRO_OPERATION_ID,
                page_url="https://example.com/pro-source-seed",
                html=self._html(1),
            ),
            self._meter(_USER_ID, _JULY),
        )
        self.subscriptions.upsert(_USER_ID, {"plan": "basic", "status": "canceled"})
        source_request = self._request(
            _SOURCE_OPERATION_ID,
            page_url="https://example.com/source-boundary",
            html=self._html(60, words_per_sentence=260),
        )
        self._submit(_USER_ID, source_request, self._meter(_USER_ID, _JULY))

        record = self.preloads.get_by_id(_USER_ID, _SOURCE_OPERATION_ID)
        operation = self.usage.get_operation(_USER_ID, _SOURCE_OPERATION_ID)
        context = self.runner.calls[1][4]
        self.assertEqual(record["source_token_limit"], self.pro.source_tokens_per_article)
        self.assertGreater(record["source_tokens_analyzed"], self.basic.source_tokens_per_article)
        self.assertLessEqual(record["source_tokens_analyzed"], self.pro.source_tokens_per_article)
        self.assertEqual(operation.source_tokens_per_article, self.pro.source_tokens_per_article)
        self.assertEqual(context["source_token_limit"], self.pro.source_tokens_per_article)

    def test_rollover_account_isolation_upgrade_and_existing_retry_keep_correct_allowances(
        self,
    ) -> None:
        self.subscriptions.upsert(_USER_ID, self._subscription("pro"))
        pro_request = self._request(
            _PRO_OPERATION_ID,
            page_url="https://example.com/pinned-operation",
            html=self._html(self.basic.sentences_per_article + 10),
        )
        self._submit(_USER_ID, pro_request, self._meter(_USER_ID, _JULY))
        self.subscriptions.upsert(_USER_ID, {"plan": "basic", "status": "canceled"})

        august_meter = self._meter(_USER_ID, _AUGUST)
        self.assertEqual(
            august_meter.processing_allowance().sentences_per_article,
            self.basic.sentences_per_article,
        )
        pinned = august_meter.processing_allowance(_PRO_OPERATION_ID)
        self.assertEqual(pinned.month, "2026-07")
        self.assertEqual(pinned.sentences_per_article, self.pro.sentences_per_article)
        self.assertEqual(pinned.source_tokens_per_article, self.pro.source_tokens_per_article)

        calls_before_retry = len(self.runner.calls)
        retry = self._submit(_USER_ID, pro_request, august_meter)
        retried_record = self.preloads.get_by_id(_USER_ID, _PRO_OPERATION_ID)
        self.assertEqual(retry.preload.id, _PRO_OPERATION_ID)
        self.assertEqual(len(self.runner.calls), calls_before_retry)
        self.assertEqual(retried_record["usage_month"], "2026-07")
        self.assertEqual(retried_record["sentence_limit"], self.pro.sentences_per_article)
        self.assertEqual(retried_record["source_token_limit"], self.pro.source_tokens_per_article)

        other_meter = self._meter(_SECOND_USER_ID, _JULY)
        other_allowance = other_meter.processing_allowance()
        self.assertEqual(other_allowance.month, "2026-07")
        self.assertEqual(other_allowance.sentences_per_article, self.basic.sentences_per_article)
        self.assertEqual(
            other_allowance.source_tokens_per_article, self.basic.source_tokens_per_article
        )

        self._submit(
            _SECOND_USER_ID,
            self._request(
                _UPGRADE_OPERATION_ID,
                page_url="https://example.com/upgrade-basic",
                html=self._html(1),
            ),
            other_meter,
        )
        self.subscriptions.upsert(_SECOND_USER_ID, self._subscription("pro"))
        upgraded = self._meter(_SECOND_USER_ID, _JULY).processing_allowance()
        self.assertEqual(upgraded.sentences_per_article, self.pro.sentences_per_article)
        self.assertEqual(upgraded.source_tokens_per_article, self.pro.source_tokens_per_article)

    def test_durable_shadow_retains_processing_caps_without_monthly_admission_effects(
        self,
    ) -> None:
        self.subscriptions.upsert(_USER_ID, self._subscription("pro"))
        shadow_meter = self._meter(_USER_ID, _JULY, durable_shadow=True)
        self._submit(
            _USER_ID,
            self._request(
                _SHADOW_OPERATION_ID,
                page_url="https://example.com/shadow-pro-seed",
                html=self._html(1),
            ),
            shadow_meter,
        )

        month = self.usage.get_month(_USER_ID, "2026-07")
        self.assertEqual(month["sentences_per_article"], self.pro.sentences_per_article)
        self.assertEqual(month["source_tokens_per_article"], self.pro.source_tokens_per_article)
        self.assertIsNone(month["plan_id"])
        self.assertEqual(month["article_limit"], 0)
        self.assertEqual(month["chat_limit"], 0)
        self.assertEqual(month["cost_micro_usd_limit"], 0)
        self.assertEqual(month["reserved_articles"], 0)
        self.assertEqual(month["reserved_chats"], 0)
        self.assertEqual(month["reserved_cost_micro_usd"], 0)

        self.subscriptions.upsert(_USER_ID, {"plan": "basic", "status": "canceled"})
        downgraded_shadow_meter = self._meter(_USER_ID, _JULY, durable_shadow=True)
        retained = downgraded_shadow_meter.processing_allowance()
        self.assertEqual(retained.sentences_per_article, self.pro.sentences_per_article)
        self.assertEqual(retained.source_tokens_per_article, self.pro.source_tokens_per_article)
        self._submit(
            _USER_ID,
            self._request(
                _SHADOW_CURRENT_OPERATION_ID,
                page_url="https://example.com/shadow-current-month",
                html=self._html(self.basic.sentences_per_article + 10),
            ),
            downgraded_shadow_meter,
        )
        record = self.preloads.get_by_id(_USER_ID, _SHADOW_CURRENT_OPERATION_ID)
        self.assertEqual(record["sentence_limit"], self.pro.sentences_per_article)
        self.assertEqual(record["source_token_limit"], self.pro.source_tokens_per_article)

        next_month = self._meter(_USER_ID, _AUGUST, durable_shadow=True).processing_allowance()
        other_account = self._meter(
            _SECOND_USER_ID,
            _JULY,
            durable_shadow=True,
        ).processing_allowance()
        self.assertEqual(next_month.sentences_per_article, self.basic.sentences_per_article)
        self.assertEqual(next_month.source_tokens_per_article, self.basic.source_tokens_per_article)
        self.assertEqual(other_account.sentences_per_article, self.basic.sentences_per_article)
        self.assertEqual(other_account.source_tokens_per_article, self.basic.source_tokens_per_article)


if __name__ == "__main__":
    unittest.main()
