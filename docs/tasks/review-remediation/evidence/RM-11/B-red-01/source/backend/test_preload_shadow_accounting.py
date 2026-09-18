"""Integration regressions for durable shadow preload accounting."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import core.pipeline as pipeline
from accounts.storage import JsonSubscriptionRepository
from core.usage_costs import ModelRate
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import PagePreloadRequest
from services import preloading
from services.usage_meter import UsageMeter
from storage.json_list_store import write_json_list
from storage.preload_content_store import FilesystemPreloadContentStore

_HTML = (
    "<article><p>This long article paragraph gives the deferred shadow workflow enough "
    "content to establish a durable operation before any provider work begins.</p>"
    "<p>A second realistic paragraph makes the content extraction and retry boundaries "
    "independent of a private model response.</p></article>"
)
_PAGE_URL = "https://example.com/durable-shadow"
_USER_ID = "shadow-user"
_OPERATION_ID = "019b63f8-f600-7000-8000-000000000401"


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
        self.calls.append((user_id, page_url, preload_id, learner_profile_fingerprint, usage_context))


class ShadowPreloadAccountingTests(unittest.TestCase):
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
                "OPENAI_RATE_CARD_VERSION": "shadow-test",
                "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
            },
        )
        self._rate_environment.start()

    def tearDown(self) -> None:
        self._rate_environment.stop()
        self._temporary_directory.cleanup()

    def _request(self, *, operation_id: str = _OPERATION_ID) -> PagePreloadRequest:
        return PagePreloadRequest(
            page_url=_PAGE_URL,
            page_title="Durable shadow article",
            html=_HTML,
            operation_id=operation_id,
        )

    def _meter(self, user_id: str = _USER_ID, *, now: datetime | None = None) -> UsageMeter:
        return UsageMeter(
            self.subscriptions,
            self.usage,
            user_id,
            rate=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "shadow-test"),
            now=now,
            reservation_enabled=False,
            durable_shadow=True,
        )

    def _submit(self, *, user_id: str = _USER_ID, meter: UsageMeter | None = None):
        return preloading.submit_preload(
            self.preloads,
            self.runner,
            self.content,
            user_id,
            self._request(),
            usage_meter=meter or self._meter(user_id),
        )

    def _run_success(self, *, provider_calls: list[str] | None = None) -> None:
        def split(*_args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            if provider_calls is not None:
                provider_calls.append("split")
            return ["A durable shadow sentence."]

        with (
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            preloading.run_preload_job(
                self.preloads,
                self.subscriptions,
                self.usage,
                self.content,
                *self.runner.calls[0][:4],
            )

    def test_shadow_marker_failure_prevents_provider_dispatch(self) -> None:
        self._submit()
        provider_called = mock.Mock()

        def split(*_args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            provider_called()
            return ["This provider call must be fenced by durable evidence."]

        with (
            mock.patch.object(UsageMeter, "save_result", side_effect=OSError("marker unavailable")),
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
        ):
            preloading.run_preload_job(
                self.preloads,
                self.subscriptions,
                self.usage,
                self.content,
                *self.runner.calls[0][:4],
            )

        provider_called.assert_not_called()
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertNotEqual(record["status"], "ready")
        self.assertEqual(operation.dispatch_evidence_state, "not_dispatched")

    def test_shadow_success_settles_before_ready_and_replay_does_not_redispatch(self) -> None:
        self._submit()
        provider_calls: list[str] = []
        self._run_success(provider_calls=provider_calls)

        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["accounting_mode"], "shadow")
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.accounting_mode, "shadow")
        self.assertEqual(operation.shadow_outcome, "success")
        self.assertEqual(month["articles"], 1)
        self.assertEqual(month["tokens"], 5)
        self.assertGreater(month["shadow_cost_micro_usd"], 0)

        self._run_success(provider_calls=provider_calls)
        after_replay = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(provider_calls, ["split"])
        self.assertEqual(after_replay["articles"], 1)
        self.assertEqual(after_replay["tokens"], 5)

    def test_shadow_ttl_replay_uses_settled_evidence_without_provider(self) -> None:
        self._submit()
        self._run_success()
        records = json.loads((Path(self._temporary_directory.name) / "usage.json").read_text())
        write_json_list(
            Path(self._temporary_directory.name) / "usage.json",
            [record for record in records if record.get("record_type") != "usage_result"],
        )
        provider = mock.Mock(side_effect=AssertionError("TTL replay must not redispatch"))

        with mock.patch.object(preloading, "_split_sentences", provider):
            preloading.run_preload_job(
                self.preloads,
                self.subscriptions,
                self.usage,
                self.content,
                *self.runner.calls[0][:4],
            )

        provider.assert_not_called()
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "success")

    def test_shadow_operations_are_scoped_by_account_and_pinned_month(self) -> None:
        july = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
        august = datetime(2026, 8, 1, 0, 1, tzinfo=UTC)
        self._submit(user_id="shadow-july", meter=self._meter("shadow-july", now=july))
        self._submit(user_id="shadow-august", meter=self._meter("shadow-august", now=august))

        july_operation = self.usage.get_operation("shadow-july", _OPERATION_ID)
        august_operation = self.usage.get_operation("shadow-august", _OPERATION_ID)
        self.assertEqual(july_operation.month, "2026-07")
        self.assertEqual(august_operation.month, "2026-08")
        self.assertEqual(july_operation.accounting_mode, "shadow")
        self.assertEqual(august_operation.accounting_mode, "shadow")


if __name__ == "__main__":
    unittest.main()
