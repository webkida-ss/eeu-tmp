"""Adversarial regressions for durable dispatch evidence and recovery."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from accounts.storage import JsonSubscriptionRepository
from core.pipeline import PipelineError, UsageTally
from core.plans import PlanLimits
from core.usage_costs import ModelRate
from repositories.dynamodb_billing_repositories import DynamoUsageRepository
from repositories.usage_repository import (
    JsonUsageRepository,
    UsageOperationConflict,
    UsageOperationStateError,
    UsageResultTooLarge,
)
from schemas import ChatResponse
from services.preloading import _configure_preload_dispatch_marker
from services.synchronous_execution import (
    SynchronousExecution,
    _configure_synchronous_dispatch_marker,
)
from services.usage_meter import UsageMeter
from storage.dynamodb_keys import usage_operation_sk, usage_result_sk, user_pk
from storage.dynamodb_store import DOCUMENT_ATTRIBUTE
from storage.json_list_store import write_json_list
from test_usage_repository import NOW, _MemoryDynamoStore, reservation

_USER_ID = "0190f4c0-0000-7000-8000-000000000001"
_RATE = ModelRate("test-model", 10, 20, "rates-v1")
_PLAN = PlanLimits("basic", 10, 10, 50, 12_000, 1_000, 200_000)
_PRIVATE_RESPONSE = "Private provider response that must remain TTL-bound."


def _operation_record(records: list[dict], operation_id: str) -> dict:
    return next(
        record
        for record in records
        if record.get("record_type") == "usage_operation"
        and record.get("operation_id") == operation_id
    )


class _FailingMarkerJsonUsageRepository(JsonUsageRepository):
    def save_result(self, user_id: str, operation_id: str, result: dict) -> dict:
        if result.get("state") == "dispatching":
            raise OSError("durable dispatch marker unavailable")
        return super().save_result(user_id, operation_id, result)


class JsonUsageEvidenceRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(self._temporary_directory.name)
        self.path = directory / "usage.json"
        self.repository = JsonUsageRepository(self.path)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_private_completed_result_expiry_preserves_measured_settlement_once(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000301",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
            },
        )
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "chat",
                "state": "completed",
                "response": {"reply": _PRIVATE_RESPONSE},
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "actual_cost_micro_usd": 17,
                },
            },
        )
        records = json.loads(self.path.read_text())
        write_json_list(
            self.path,
            [record for record in records if record.get("record_type") != "usage_result"],
        )
        first_adapter = JsonUsageRepository(self.path)
        second_adapter = JsonUsageRepository(self.path)
        barrier = threading.Barrier(3)

        def reclaim(adapter: JsonUsageRepository) -> int:
            barrier.wait()
            return adapter.reclaim_expired(request.user_id, NOW)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(reclaim, adapter) for adapter in (first_adapter, second_adapter)
            ]
            barrier.wait()
            reclaimed = [future.result(timeout=2) for future in futures]

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        month = self.repository.get_month(request.user_id, request.month)
        evidence = _operation_record(json.loads(self.path.read_text()), request.operation_id)
        self.assertEqual(sum(reclaimed), 1)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, 17)
        self.assertEqual(month["committed_cost_micro_usd"], 17)
        self.assertEqual(month["tokens"], 5)
        self.assertEqual(evidence["dispatch_evidence_state"], "settled")
        self.assertEqual(evidence["dispatch_usage"]["actual_cost_micro_usd"], 17)
        self.assertNotIn("response", evidence)
        self.assertNotIn(_PRIVATE_RESPONSE, json.dumps(evidence, sort_keys=True))

    def test_new_no_dispatch_releases_but_unknown_legacy_operation_remains_reserved(self) -> None:
        new_request = reservation(
            "019b63f8-f600-7000-8000-000000000302",
            chats=1,
            expires_at=NOW,
        )
        legacy_request = reservation(
            "019b63f8-f600-7000-8000-000000000303",
            chats=1,
            expires_at=NOW,
        )
        self.repository.reserve(new_request)
        self.repository.reserve(legacy_request)
        records = json.loads(self.path.read_text())
        legacy_record = _operation_record(records, legacy_request.operation_id)
        legacy_record.pop("dispatch_evidence_state", None)
        legacy_record.pop("evidence_version", None)
        legacy_record.pop("dispatch_evidence_version", None)
        legacy_record.pop("kind", None)
        legacy_record.pop("dispatch_kind", None)
        legacy_record.pop("dispatch_usage", None)
        write_json_list(self.path, records)

        reclaimed = self.repository.reclaim_expired(_USER_ID, NOW)

        self.assertEqual(reclaimed, 1)
        self.assertEqual(
            self.repository.get_operation(_USER_ID, new_request.operation_id).state,
            "released",
        )
        self.assertEqual(
            self.repository.get_operation(_USER_ID, legacy_request.operation_id).state,
            "reserved",
        )

    def test_stale_dispatch_marker_cannot_downgrade_completed_evidence(self) -> None:
        request = reservation("019b63f8-f600-7000-8000-000000000308", cost_micro_usd=13)
        self.repository.reserve(request)
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
            },
        )
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "chat",
                "state": "completed",
                "response": {"reply": _PRIVATE_RESPONSE},
                "usage": {"actual_cost_micro_usd": 17},
            },
        )

        with self.assertRaises(UsageOperationStateError):
            self.repository.save_result(
                request.user_id,
                request.operation_id,
                {
                    "kind": "chat",
                    "state": "dispatching",
                    "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
                },
            )

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(operation.dispatch_evidence_state, "completed")
        self.assertEqual(operation.dispatch_usage["actual_cost_micro_usd"], 17)

    def test_completion_and_reclaim_settle_once_under_concurrent_adapters(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000309",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
            },
        )
        completing_adapter = JsonUsageRepository(self.path)
        reclaiming_adapter = JsonUsageRepository(self.path)
        barrier = threading.Barrier(3)

        def complete() -> Exception | None:
            barrier.wait()
            try:
                completing_adapter.save_result(
                    request.user_id,
                    request.operation_id,
                    {
                        "kind": "chat",
                        "state": "completed",
                        "response": {"reply": _PRIVATE_RESPONSE},
                        "usage": {"actual_cost_micro_usd": 17},
                    },
                )
            except Exception as exc:  # The reclaim winner may fence the late completion.
                return exc
            return None

        def reclaim() -> int:
            barrier.wait()
            return reclaiming_adapter.reclaim_expired(request.user_id, NOW)

        with ThreadPoolExecutor(max_workers=2) as executor:
            completion = executor.submit(complete)
            reclamation = executor.submit(reclaim)
            barrier.wait()
            completion_error = completion.result(timeout=2)
            reclamation_count = reclamation.result(timeout=2)

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        month = self.repository.get_month(request.user_id, request.month)
        self.assertTrue(
            completion_error is None or isinstance(completion_error, UsageOperationStateError)
        )
        self.assertIn(reclamation_count, (0, 1))
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.dispatch_evidence_state, "settled")
        self.assertIn(operation.actual_cost_micro_usd, (request.cost_micro_usd, 17))
        self.assertEqual(month["committed_cost_micro_usd"], operation.actual_cost_micro_usd)
        self.assertEqual(month["reserved_cost_micro_usd"], 0)

    def test_private_result_write_failure_keeps_durable_measured_evidence(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000310",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        private_response = "x" * 2_000

        with (
            mock.patch.dict("os.environ", {"SYNC_RESULT_MAX_BYTES": "100"}),
            self.assertRaises(UsageResultTooLarge),
        ):
            self.repository.save_result(
                request.user_id,
                request.operation_id,
                {
                    "kind": "chat",
                    "state": "completed",
                    "response": {"reply": private_response},
                    "usage": {"actual_cost_micro_usd": 17},
                },
            )

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(operation.dispatch_evidence_state, "completed")
        self.assertEqual(operation.dispatch_usage["actual_cost_micro_usd"], 17)
        self.assertIsNone(self.repository.get_result(request.user_id, request.operation_id))
        self.assertEqual(self.repository.reclaim_expired(request.user_id, NOW), 1)
        settled = self.repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(settled.state, "finalized")
        self.assertEqual(settled.actual_cost_micro_usd, 17)

    def test_incomplete_usage_does_not_become_measured_zero_after_reclaim(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000312",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "chat",
                "state": "completed",
                "response": {"reply": _PRIVATE_RESPONSE},
                "usage": {},
            },
        )

        self.assertEqual(self.repository.reclaim_expired(request.user_id, NOW), 1)

        settled = self.repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(settled.state, "finalized")
        self.assertEqual(settled.dispatch_usage_completeness, "conservative")
        self.assertEqual(settled.actual_cost_micro_usd, request.cost_micro_usd)
        self.assertEqual(settled.tokens, 0)

    def test_partial_usage_is_retained_when_conservative_reclaim_settles(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000313",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        self.repository.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "preload",
                "state": "completed",
                "usage": {
                    "actual_cost_micro_usd": 17,
                    "input_tokens": 3,
                    "usage_complete": False,
                },
            },
        )

        self.assertEqual(self.repository.reclaim_expired(request.user_id, NOW), 1)

        settled = self.repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(settled.state, "finalized")
        self.assertEqual(settled.dispatch_usage_completeness, "conservative")
        self.assertEqual(settled.actual_cost_micro_usd, 17)
        self.assertEqual(settled.dispatch_usage["input_tokens"], 3)
        self.assertEqual(settled.dispatch_usage["total_tokens"], 3)

    def test_arbitrary_result_kind_cannot_be_persisted_as_dispatch_evidence(self) -> None:
        request = reservation("019b63f8-f600-7000-8000-000000000314", cost_micro_usd=13)
        self.repository.reserve(request)

        with self.assertRaises(UsageOperationConflict):
            self.repository.save_result(
                request.user_id,
                request.operation_id,
                {
                    "kind": _PRIVATE_RESPONSE,
                    "state": "dispatching",
                    "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
                },
            )

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(operation.dispatch_evidence_state, "not_dispatched")
        self.assertIsNone(operation.dispatch_kind)

    def test_reclaim_and_dispatch_promotion_leave_one_terminal_outcome(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000311",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        promoting_adapter = JsonUsageRepository(self.path)
        reclaiming_adapter = JsonUsageRepository(self.path)
        barrier = threading.Barrier(3)

        def promote() -> Exception | None:
            barrier.wait()
            try:
                promoting_adapter.save_result(
                    request.user_id,
                    request.operation_id,
                    {
                        "kind": "chat",
                        "state": "dispatching",
                        "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
                    },
                )
            except Exception as exc:
                return exc
            return None

        def reclaim() -> int:
            barrier.wait()
            return reclaiming_adapter.reclaim_expired(request.user_id, NOW)

        with ThreadPoolExecutor(max_workers=2) as executor:
            promotion = executor.submit(promote)
            reclamation = executor.submit(reclaim)
            barrier.wait()
            promotion_error = promotion.result(timeout=2)
            reclamation_count = reclamation.result(timeout=2)

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        month = self.repository.get_month(request.user_id, request.month)
        self.assertTrue(
            promotion_error is None or isinstance(promotion_error, UsageOperationStateError)
        )
        self.assertIn(reclamation_count, (0, 1))
        self.assertIn(operation.state, ("finalized", "released"))
        self.assertEqual(month["reserved_cost_micro_usd"], 0)
        if operation.state == "finalized":
            self.assertEqual(operation.actual_cost_micro_usd, request.cost_micro_usd)
            self.assertEqual(operation.dispatch_evidence_state, "settled")
        else:
            self.assertEqual(operation.dispatch_evidence_state, "not_dispatched")


class DynamoUsageEvidenceRecoveryTests(unittest.TestCase):
    def test_native_private_result_deletion_preserves_conservative_settlement_once(self) -> None:
        store = _MemoryDynamoStore()
        request = reservation(
            "019b63f8-f600-7000-8000-000000000304",
            cost_micro_usd=19,
            expires_at=NOW,
        )
        first_adapter = DynamoUsageRepository(store)
        second_adapter = DynamoUsageRepository(store)
        first_adapter.reserve(request)
        first_adapter.save_result(
            request.user_id,
            request.operation_id,
            {
                "kind": "preload",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": request.cost_micro_usd},
            },
        )
        store.items.pop((user_pk(request.user_id), usage_result_sk(request.operation_id)))
        barrier = threading.Barrier(3)

        def reclaim(adapter: DynamoUsageRepository) -> int:
            barrier.wait()
            return adapter.reclaim_expired(request.user_id, NOW)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(reclaim, adapter) for adapter in (first_adapter, second_adapter)
            ]
            barrier.wait()
            reclaimed = [future.result(timeout=2) for future in futures]

        operation = first_adapter.get_operation(request.user_id, request.operation_id)
        month = first_adapter.get_month(request.user_id, request.month)
        evidence = json.loads(
            store.items[
                (user_pk(request.user_id), usage_operation_sk(request.operation_id))
            ][DOCUMENT_ATTRIBUTE]
        )
        self.assertEqual(sum(reclaimed), 1)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, request.cost_micro_usd)
        self.assertEqual(month["committed_cost_micro_usd"], request.cost_micro_usd)
        self.assertEqual(month["reserved_cost_micro_usd"], 0)
        self.assertEqual(evidence["dispatch_evidence_state"], "settled")
        self.assertNotIn("response", evidence)


class SynchronousDispatchEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        directory = Path(self._temporary_directory.name)
        subscriptions = JsonSubscriptionRepository(directory / "subscriptions.json")
        usage = _FailingMarkerJsonUsageRepository(directory / "usage.json")
        self.meter = UsageMeter(
            subscriptions,
            usage,
            _USER_ID,
            rate=_RATE,
            now=datetime.now(UTC),
            plan_loader=lambda _plan_id: _PLAN,
            reservation_enabled=True,
        )
        self.operation = self.meter.reserve(
            "019b63f8-f600-7000-8000-000000000305",
            "dispatch-marker-failure",
            "chat",
            11,
        )

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_marker_write_failure_prevents_synchronous_provider_dispatch(self) -> None:
        execution = SynchronousExecution(
            self.meter,
            self.operation,
            kind="chat",
            response_model=ChatResponse,
        )
        provider = mock.Mock()
        tally = UsageTally(rate=_RATE)

        def dispatch() -> None:
            tally.mark_dispatch_attempt()
            provider()

        with execution:
            with self.assertRaisesRegex(OSError, "dispatch marker"):
                execution.run(tally, dispatch, lambda value: ChatResponse(reply=value))

        provider.assert_not_called()

    def test_marker_write_failure_prevents_preload_provider_dispatch(self) -> None:
        provider = mock.Mock()
        tally = UsageTally(rate=_RATE)
        _configure_preload_dispatch_marker(self.meter, self.operation, tally)

        def dispatch() -> None:
            tally.mark_dispatch_attempt()
            provider()

        with self.assertRaisesRegex(OSError, "dispatch marker"):
            dispatch()

        provider.assert_not_called()

    def test_private_result_expiry_blocks_synchronous_redispatch_before_reclaim(self) -> None:
        directory = Path(self._temporary_directory.name)
        usage = JsonUsageRepository(directory / "retry-usage.json")
        meter = UsageMeter(
            JsonSubscriptionRepository(directory / "retry-subscriptions.json"),
            usage,
            _USER_ID,
            rate=_RATE,
            now=datetime.now(UTC),
            plan_loader=lambda _plan_id: _PLAN,
            reservation_enabled=True,
        )
        operation = meter.reserve(
            "019b63f8-f600-7000-8000-000000000306",
            "private-result-expiry",
            "chat",
            11,
        )
        meter.save_result(
            operation.operation_id,
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": operation.reserved_cost_micro_usd},
            },
        )
        records = json.loads((directory / "retry-usage.json").read_text())
        write_json_list(
            directory / "retry-usage.json",
            [record for record in records if record.get("record_type") != "usage_result"],
        )
        execution = SynchronousExecution(
            meter,
            meter.get_operation(operation.operation_id),
            kind="chat",
            response_model=ChatResponse,
        )
        provider = mock.Mock(return_value="must not dispatch")

        with self.assertRaises(PipelineError):
            with execution:
                execution.run(
                    UsageTally(rate=_RATE),
                    provider,
                    lambda reply: ChatResponse(reply=reply),
                )

        provider.assert_not_called()

    def test_configured_marker_authorizes_only_the_current_execution(self) -> None:
        directory = Path(self._temporary_directory.name)
        meter = UsageMeter(
            JsonSubscriptionRepository(directory / "marker-subscriptions.json"),
            JsonUsageRepository(directory / "marker-usage.json"),
            _USER_ID,
            rate=_RATE,
            now=datetime.now(UTC),
            plan_loader=lambda _plan_id: _PLAN,
            reservation_enabled=True,
        )
        operation = meter.reserve(
            "019b63f8-f600-7000-8000-000000000307",
            "same-execution-marker",
            "chat",
            11,
        )
        current_execution = UsageTally(rate=_RATE)
        _configure_synchronous_dispatch_marker(current_execution, meter, operation, "chat")

        current_execution.mark_dispatch_attempt()
        current_execution.mark_dispatch_attempt()

        new_execution = UsageTally(rate=_RATE)
        _configure_synchronous_dispatch_marker(new_execution, meter, operation, "chat")
        with self.assertRaises(UsageOperationStateError):
            new_execution.mark_dispatch_attempt()

        self.assertTrue(current_execution.any_dispatch_attempted)
        self.assertFalse(new_execution.any_dispatch_attempted)


if __name__ == "__main__":
    unittest.main()
