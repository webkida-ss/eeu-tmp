"""Crash-window regressions for durable-shadow preload recovery."""

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
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import PagePreloadRequest
from services import preloading
from services.usage_meter import UsageMeter
from storage.json_list_store import write_json_list
from storage.preload_content_store import FilesystemPreloadContentStore
from test_preload_shadow_accounting import _HTML, _PAGE_URL, _RecordingRunner

_USER_ID = "shadow-recovery-user"
_OPERATION_ID = "019b63f8-f600-7000-8000-000000000491"


class ShadowRecoveryWindowTests(unittest.TestCase):
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
                "OPENAI_RATE_CARD_VERSION": "shadow-recovery-test",
                "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
            },
        )
        self._rate_environment.start()

    def tearDown(self) -> None:
        self._rate_environment.stop()
        self._temporary_directory.cleanup()

    def _meter(self) -> UsageMeter:
        return UsageMeter(
            self.subscriptions,
            self.usage,
            _USER_ID,
            rate=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "shadow-recovery-test"),
            reservation_enabled=False,
            durable_shadow=True,
        )

    def _submit(self, operation_id: str = _OPERATION_ID) -> None:
        preloading.submit_preload(
            self.preloads,
            self.runner,
            self.content,
            _USER_ID,
            PagePreloadRequest(
                page_url=_PAGE_URL,
                page_title="Durable shadow recovery article",
                html=_HTML,
                operation_id=operation_id,
            ),
            usage_meter=self._meter(),
        )

    def _run(self, job_index: int = 0) -> None:
        preloading.run_preload_job(
            self.preloads,
            self.subscriptions,
            self.usage,
            self.content,
            *self.runner.calls[job_index][:4],
        )

    def _run_success(self) -> None:
        def split(*_args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            return ["A durable shadow recovery sentence."]

        with (
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("summary", [], []),
            ),
            mock.patch.object(preloading, "_extract_study_items", return_value=([], {})),
        ):
            self._run()

    def _expire_preload_lease(self, operation_id: str = _OPERATION_ID) -> None:
        record = self.preloads.get_by_id(_USER_ID, operation_id)
        record["status"] = "running"
        record["lease_id"] = "expired-shadow-worker"
        record["lease_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        self.preloads.save(_USER_ID, record, make_latest=False)

    def _assert_terminal_once(self, operation_id: str, *, outcome: str, articles: int) -> None:
        operation = self.usage.get_operation(_USER_ID, operation_id)
        record = self.preloads.get_by_id(_USER_ID, operation_id)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual((operation.state, operation.shadow_outcome), ("finalized", outcome))
        self.assertIn(record["status"], {"ready", "failed"})
        self.assertNotEqual(record["status"], "failed_pending_usage")
        self.assertEqual(month["articles"], articles)

    def test_marker_crash_before_completion_recovers_without_redispatch(self) -> None:
        self._submit()

        def dispatch_then_crash(*_args, **kwargs):
            kwargs["tally"].mark_dispatch_attempt()
            raise KeyboardInterrupt("crash after marker")

        with (
            mock.patch.object(preloading, "_split_sentences", side_effect=dispatch_then_crash),
            self.assertRaisesRegex(KeyboardInterrupt, "after marker"),
        ):
            self._run()

        self._expire_preload_lease()
        provider = mock.Mock(side_effect=AssertionError("recovery must not redispatch"))
        with mock.patch.object(preloading, "_split_sentences", provider):
            self._run()

        provider.assert_not_called()
        self._assert_terminal_once(_OPERATION_ID, outcome="failed_after_dispatch", articles=0)
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertGreaterEqual(month["shadow_cost_micro_usd"], operation.reserved_cost_micro_usd)

    def test_completed_private_result_crash_before_prepare_repairs_success_without_provider(
        self,
    ) -> None:
        self._submit()
        with (
            mock.patch.object(
                UsageMeter,
                "prepare_shadow_settlement",
                side_effect=KeyboardInterrupt("crash before prepare"),
            ),
            self.assertRaisesRegex(KeyboardInterrupt, "before prepare"),
        ):
            self._run_success()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.dispatch_evidence_state, "completed")
        self.assertIsNotNone(self.usage.get_result(_USER_ID, _OPERATION_ID))
        self._expire_preload_lease()
        provider = mock.Mock(side_effect=AssertionError("recovery must not redispatch"))
        with mock.patch.object(preloading, "_split_sentences", provider):
            self._run()

        provider.assert_not_called()
        self._assert_terminal_once(_OPERATION_ID, outcome="success", articles=1)

    def test_prepare_failure_before_commit_replays_retained_result_once(self) -> None:
        self._submit()
        with mock.patch.object(
            UsageMeter,
            "prepare_shadow_settlement",
            side_effect=OSError("prepare unavailable"),
        ):
            self._run_success()

        pending = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(pending["status"], "ready_pending_usage")
        self.assertIsNone(operation.shadow_pending_outcome)
        self.assertIsNotNone(self.usage.get_result(_USER_ID, _OPERATION_ID))

        provider = mock.Mock(side_effect=AssertionError("recovery must not redispatch"))
        with mock.patch.object(preloading, "_split_sentences", provider):
            self._run()

        provider.assert_not_called()
        self._assert_terminal_once(_OPERATION_ID, outcome="success", articles=1)

    def test_expired_execution_with_ttl_deleted_private_result_settles_after_dispatch(
        self,
    ) -> None:
        self._submit()
        with (
            mock.patch.object(
                UsageMeter,
                "prepare_shadow_settlement",
                side_effect=KeyboardInterrupt("crash before prepare"),
            ),
            self.assertRaisesRegex(KeyboardInterrupt, "before prepare"),
        ):
            self._run_success()

        durable_measurement = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(durable_measurement.dispatch_usage_completeness, "measured")
        expected_cost = durable_measurement.dispatch_usage["actual_cost_micro_usd"]
        expected_tokens = durable_measurement.dispatch_usage["total_tokens"]
        records = json.loads((Path(self._temporary_directory.name) / "usage.json").read_text())
        for record in records:
            if record.get("record_type") == "usage_result":
                record["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        write_json_list(Path(self._temporary_directory.name) / "usage.json", records)
        self.assertIsNone(self.usage.get_result(_USER_ID, _OPERATION_ID))
        self._expire_preload_lease()
        reclaim_now = datetime.now(UTC)
        self.assertEqual(
            self._meter().claim_execution(
                _OPERATION_ID,
                "expired-shadow-execution",
                reclaim_now,
                reclaim_now - timedelta(seconds=1),
            ),
            "recovered",
        )

        provider = mock.Mock(side_effect=AssertionError("TTL recovery must not redispatch"))
        with mock.patch.object(preloading, "_split_sentences", provider):
            self._run()

        provider.assert_not_called()
        self._assert_terminal_once(_OPERATION_ID, outcome="failed_after_dispatch", articles=0)
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(
            (
                operation.dispatch_usage_completeness,
                operation.actual_cost_micro_usd,
                operation.tokens,
            ),
            ("measured", expected_cost, expected_tokens),
        )
        self.assertEqual(
            (month["shadow_cost_micro_usd"], month["tokens"]),
            (expected_cost, expected_tokens),
        )

    def test_missing_content_after_dispatch_conserves_cost_instead_of_zero(self) -> None:
        for job_index, (state, operation_id) in enumerate(
            (
                ("dispatching", "019b63f8-f600-7000-8000-000000000492"),
                ("completed", "019b63f8-f600-7000-8000-000000000493"),
            )
        ):
            with self.subTest(state=state):
                self._submit(operation_id)
                meter = self._meter()
                meter.save_result(
                    operation_id,
                    {
                        "kind": "preload",
                        "state": state,
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": 2,
                            "total_tokens": 5,
                            "actual_cost_micro_usd": 17,
                            "usage_complete": state == "completed",
                        },
                    },
                )
                self.content.delete(_USER_ID, operation_id)
                provider = mock.Mock(
                    side_effect=AssertionError("content recovery must not redispatch")
                )
                with mock.patch.object(preloading, "_split_sentences", provider):
                    self._run(job_index)

                provider.assert_not_called()
                self._assert_terminal_once(
                    operation_id, outcome="failed_after_dispatch", articles=0
                )
                operation = self.usage.get_operation(_USER_ID, operation_id)
                month = self.usage.get_month(_USER_ID, operation.month)
                self.assertGreaterEqual(
                    month["shadow_cost_micro_usd"], operation.reserved_cost_micro_usd
                )

    def test_live_preload_and_execution_claim_wait_without_settlement(self) -> None:
        self._submit()
        now = datetime.now(UTC)
        record = self.preloads.claim_processing(
            _USER_ID,
            _OPERATION_ID,
            self.runner.calls[0][3],
            lease_id="live-shadow-worker",
            now=now,
            lease_expires_at=now + timedelta(minutes=5),
        )
        self.assertIsNotNone(record)
        self.assertEqual(
            self._meter().claim_execution(
                _OPERATION_ID,
                "live-shadow-worker",
                now,
                now + timedelta(minutes=5),
            ),
            "claimed",
        )

        provider = mock.Mock(side_effect=AssertionError("live worker must be awaited"))
        with mock.patch.object(preloading, "_split_sentences", provider):
            self._run()

        provider.assert_not_called()
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        current = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual((operation.state, operation.shadow_pending_outcome), ("reserved", None))
        self.assertEqual(current["status"], "running")


if __name__ == "__main__":
    unittest.main()
