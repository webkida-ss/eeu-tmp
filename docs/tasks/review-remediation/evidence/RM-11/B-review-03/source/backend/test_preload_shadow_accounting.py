"""Integration regressions for durable shadow preload accounting."""

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
from repositories.dynamodb_page_preload_repository import DynamoPagePreloadRepository
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import PagePreloadRequest
from services import preloading
from services.usage_meter import UsageMeter
from storage.json_list_store import write_json_list
from storage.preload_content_store import FilesystemPreloadContentStore
from test_usage_repository import _MemoryDynamoStore

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
        self.calls.append(
            (user_id, page_url, preload_id, learner_profile_fingerprint, usage_context)
        )


class _SettlementBeforeReadyRepository(JsonPagePreloadRepository):
    def __init__(self, path: Path, usage: JsonUsageRepository) -> None:
        super().__init__(path)
        self._usage = usage
        self.checked_ready_publication = False

    def finish_processing(self, user_id, preload_id, fingerprint, record, **kwargs):
        if record.get("status") == "ready":
            operation = self._usage.get_operation(user_id, str(record["operation_id"]))
            if operation is None:
                raise AssertionError("shadow settlement must complete before ready publication")
            month = self._usage.get_month(user_id, operation.month)
            if (
                operation.state != "finalized"
                or operation.accounting_mode != "shadow"
                or operation.shadow_outcome != "success"
                or month["articles"] != 1
            ):
                raise AssertionError("shadow settlement must complete before ready publication")
            self.checked_ready_publication = True
        return super().finish_processing(user_id, preload_id, fingerprint, record, **kwargs)


class _LostPublicationRepository(JsonPagePreloadRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.blocked_publications = 0

    def finish_processing(self, user_id, preload_id, fingerprint, record, **kwargs):
        if record.get("status") in {"ready", "failed"}:
            self.blocked_publications += 1
            return False
        return super().finish_processing(user_id, preload_id, fingerprint, record, **kwargs)


class _DynamoPreloadStore(_MemoryDynamoStore):
    """Extends the faithful usage-store fixture with page-document writes."""

    def get_document(self, pk, sk, *, consistent_read=False):
        del consistent_read
        return super().get_document(pk, sk)

    def put_document(self, pk, sk, document, *, extra_attributes=None):
        self.items[(pk, sk)] = {
            "pk": pk,
            "sk": sk,
            "document": json.dumps(document),
            **(extra_attributes or {}),
        }

    def put_documents_atomically(self, entries):
        for pk, sk, document, extra_attributes in entries:
            self.put_document(pk, sk, document, extra_attributes=extra_attributes)


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
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(operation.shadow_outcome, "failed_before_dispatch")
        self.assertEqual(operation.dispatch_evidence_state, "settled")
        self.assertEqual(month["articles"], 0)
        self.assertEqual(month["tokens"], 0)

    def test_new_disabled_preload_uses_a_durable_shadow_clone(self) -> None:
        disabled_meter = UsageMeter(
            self.subscriptions,
            self.usage,
            _USER_ID,
            rate=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "shadow-test"),
            reservation_enabled=False,
        )

        self._submit(meter=disabled_meter)

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertFalse(disabled_meter.durable_shadow)
        self.assertEqual(operation.accounting_mode, "shadow")
        self.assertEqual(record["accounting_mode"], "shadow")
        self.assertEqual(record["shadow_version"], 1)

    def test_legacy_inflight_shadow_record_fails_closed_without_provider_dispatch(self) -> None:
        preload_id = "019b63f8-f600-7000-8000-000000000402"
        fingerprint = "legacy-shadow-profile"
        self.preloads.save(
            _USER_ID,
            {
                "id": preload_id,
                "operation_id": preload_id,
                "page_url": "https://example.com/legacy-shadow",
                "learner_profile_fingerprint": fingerprint,
                "status": "processing",
                "shadow_usage": {"operation_id": preload_id},
            },
            make_latest=False,
        )
        provider = mock.Mock(side_effect=AssertionError("legacy record must not dispatch"))

        with mock.patch.object(preloading, "_split_sentences", provider):
            preloading.run_preload_job(
                self.preloads,
                self.subscriptions,
                self.usage,
                self.content,
                _USER_ID,
                "https://example.com/legacy-shadow",
                preload_id,
                fingerprint,
            )

        provider.assert_not_called()
        record = self.preloads.get_by_id(_USER_ID, preload_id)
        self.assertEqual(record["status"], "failed")
        self.assertIn("cannot be recovered safely", record["error"])

    def test_shadow_handoff_failure_settles_before_content_cleanup(self) -> None:
        with (
            mock.patch.object(
                self.content,
                "put_if_absent",
                side_effect=OSError("content unavailable"),
            ),
            self.assertRaisesRegex(OSError, "content unavailable"),
        ):
            self._submit()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "failed_before_dispatch")
        self.assertEqual(record["status"], "failed")
        self.assertFalse(record["content_retirement_pending"])
        self.assertEqual(month["articles"], 0)
        self.assertEqual(month["tokens"], 0)

    def test_shadow_success_settles_before_ready_and_replay_does_not_redispatch(self) -> None:
        self.preloads = _SettlementBeforeReadyRepository(
            Path(self._temporary_directory.name) / "preloads.json",
            self.usage,
        )
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
        self.assertTrue(self.preloads.checked_ready_publication)

        self._run_success(provider_calls=provider_calls)
        after_replay = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(provider_calls, ["split"])
        self.assertEqual(after_replay["articles"], 1)
        self.assertEqual(after_replay["tokens"], 5)

    def test_shadow_crash_after_settlement_recovers_after_ttl_without_provider(self) -> None:
        self._submit()
        original_settle = UsageMeter.settle_shadow

        def settle_then_crash(meter, operation_id):
            original_settle(meter, operation_id)
            raise KeyboardInterrupt("simulated crash after shadow settlement")

        with (
            mock.patch.object(UsageMeter, "settle_shadow", new=settle_then_crash),
            self.assertRaisesRegex(KeyboardInterrupt, "after shadow settlement"),
        ):
            self._run_success()

        settled = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(settled.state, "finalized")
        self.assertEqual(settled.shadow_outcome, "success")
        pending = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        pending["status"] = "processing"
        pending.pop("lease_id", None)
        pending.pop("lease_expires_at", None)
        self.preloads.save(_USER_ID, pending, make_latest=False)
        records = json.loads((Path(self._temporary_directory.name) / "usage.json").read_text())
        expired_result_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        for stored in records:
            if stored.get("record_type") == "usage_result":
                stored["expires_at"] = expired_result_at
        write_json_list(
            Path(self._temporary_directory.name) / "usage.json",
            records,
        )
        self.assertIsNone(self.usage.get_result(_USER_ID, _OPERATION_ID))
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
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "success")
        self.assertEqual(record["status"], "failed")
        self.assertIn("no longer available", record["error"])
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(month["articles"], 1)
        self.assertEqual(month["tokens"], 5)

    def test_shadow_provider_failure_settles_cost_without_an_article(self) -> None:
        self._submit()

        def split(*_args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            raise RuntimeError("provider private detail")

        with mock.patch.object(preloading, "_split_sentences", side_effect=split):
            preloading.run_preload_job(
                self.preloads,
                self.subscriptions,
                self.usage,
                self.content,
                *self.runner.calls[0][:4],
            )

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "failed_after_dispatch")
        self.assertEqual(record["status"], "failed")
        self.assertNotIn("provider private detail", record["error"])
        self.assertEqual(month["articles"], 0)
        self.assertEqual(month["tokens"], 5)
        self.assertGreater(month["shadow_cost_micro_usd"], 0)

    def test_shadow_incomplete_usage_keeps_known_cost_above_the_estimated_floor(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            _USER_ID,
            rate=ModelRate(pipeline.OPENAI_MODEL, 3_000_000, 4_000_000, "shadow-test"),
            reservation_enabled=False,
            durable_shadow=True,
        )
        with mock.patch.object(preloading, "estimate_article_cost_micro_usd", return_value=13):
            self._submit(meter=meter)

        self._run_success()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.actual_cost_micro_usd, 17)
        self.assertEqual(month["shadow_cost_micro_usd"], 17)
        self.assertEqual(month["tokens"], 5)

    def test_shadow_oversized_private_result_settles_failure_without_an_article(self) -> None:
        self._submit()
        original_save_result = UsageMeter.save_result

        def reject_completed_result(meter, operation_id, result):
            if result.get("state") == "completed":
                raise ValueError("private result exceeded its retention limit")
            return original_save_result(meter, operation_id, result)

        with mock.patch.object(UsageMeter, "save_result", new=reject_completed_result):
            self._run_success()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "failed_after_dispatch")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(month["articles"], 0)
        self.assertGreater(month["shadow_cost_micro_usd"], 0)

    def test_dynamo_page_limit_fails_before_shadow_success_settlement(self) -> None:
        self.preloads = DynamoPagePreloadRepository(_DynamoPreloadStore())
        self.runner = _RecordingRunner()
        self._submit()
        provider_calls: list[str] = []

        def split(*_args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            provider_calls.append("split")
            return ["A durable shadow sentence."]

        with (
            mock.patch.dict(os.environ, {"DYNAMODB_PRELOAD_MAX_BYTES": "3500"}),
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("x" * 4_000, [], []),
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

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(provider_calls, ["split"])
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "failed_after_dispatch")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(month["articles"], 0)
        self.assertEqual(month["tokens"], 5)

    def test_json_publication_does_not_inherit_the_dynamo_size_ceiling(self) -> None:
        self._submit()

        def split(*_args, **kwargs):
            tally = kwargs["tally"]
            tally.mark_dispatch_attempt()
            tally.add_response(
                types.SimpleNamespace(
                    model=pipeline.OPENAI_MODEL,
                    usage=types.SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
                )
            )
            return ["A durable shadow sentence."]

        with (
            mock.patch.dict(os.environ, {"DYNAMODB_PRELOAD_MAX_BYTES": "1"}),
            mock.patch.object(preloading, "_split_sentences", side_effect=split),
            mock.patch.object(
                preloading,
                "_analyze_sentences",
                return_value=("x" * 4_000, [], []),
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

        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        self.assertEqual(record["status"], "ready")
        self.assertEqual(operation.shadow_outcome, "success")
        self.assertEqual(record["summary"], "x" * 4_000)

    def test_shadow_lost_publication_keeps_settlement_and_content_for_recovery(self) -> None:
        self.preloads = _LostPublicationRepository(
            Path(self._temporary_directory.name) / "preloads.json"
        )
        self._submit()
        self._run_success()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.shadow_outcome, "success")
        self.assertEqual(record["status"], "running")
        self.assertGreater(self.preloads.blocked_publications, 0)
        self.assertIsNotNone(self.content.get(_USER_ID, _OPERATION_ID))
        self.assertEqual(month["articles"], 1)
        self.assertEqual(month["tokens"], 5)

    def test_shadow_recovers_an_expired_worker_lease_without_duplicate_accounting(self) -> None:
        self._submit()
        expired = datetime.now(UTC) - timedelta(minutes=1)
        first_lease = "expired-worker-lease"
        claimed = self.preloads.claim_processing(
            _USER_ID,
            _OPERATION_ID,
            self.runner.calls[0][3],
            lease_id=first_lease,
            now=expired - timedelta(minutes=1),
            lease_expires_at=expired,
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(
            self._meter().claim_execution(
                _OPERATION_ID,
                first_lease,
                expired - timedelta(minutes=1),
                expired,
            ),
            "claimed",
        )

        self._run_success()

        operation = self.usage.get_operation(_USER_ID, _OPERATION_ID)
        record = self.preloads.get_by_id(_USER_ID, _OPERATION_ID)
        month = self.usage.get_month(_USER_ID, operation.month)
        self.assertEqual(record["status"], "ready")
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(month["articles"], 1)
        self.assertEqual(month["tokens"], 5)

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

        self.preloads = JsonPagePreloadRepository(
            Path(self._temporary_directory.name) / "rollover-preloads.json"
        )
        self.runner = _RecordingRunner()
        self._submit(meter=self._meter(now=july))
        self._run_success()
        retry = self._submit(meter=self._meter(now=august))
        original_month = self.usage.get_month(_USER_ID, "2026-07")
        rollover_month = self.usage.get_month(_USER_ID, "2026-08")
        self.assertTrue(retry.ready)
        self.assertEqual(original_month["articles"], 1)
        self.assertEqual(original_month["tokens"], 5)
        self.assertEqual(rollover_month["articles"], 0)
        self.assertEqual(rollover_month["tokens"], 0)


if __name__ == "__main__":
    unittest.main()
