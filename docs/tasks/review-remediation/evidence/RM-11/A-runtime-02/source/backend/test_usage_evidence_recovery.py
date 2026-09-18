"""Adversarial regressions for durable dispatch evidence and recovery."""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import threading
import unittest
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty
from typing import Any
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


def _run_worker_process(
    worker: Callable[[], int],
    ready: Any,
    release: Any,
    outcomes: Any,
) -> None:
    ready.set()
    if not release.wait(timeout=2):
        outcomes.put(("error", "test coordinator did not release the worker"))
        return
    try:
        outcomes.put(("result", worker()))
    except Exception as exc:
        outcomes.put(("error", repr(exc)))


def _run_bounded_workers(*workers: Callable[[], int]) -> list[int]:
    """Run independent file-lock contenders in terminable child processes."""
    context = multiprocessing.get_context("fork")
    release = context.Event()
    ready = [context.Event() for _ in workers]
    outcomes = context.Queue()
    processes = [
        context.Process(
            target=_run_worker_process,
            args=(worker, ready[index], release, outcomes),
        )
        for index, worker in enumerate(workers)
    ]
    for process in processes:
        process.start()
    results: list[int] = []
    errors: list[str] = []
    try:
        if not all(event.wait(timeout=2) for event in ready):
            raise AssertionError("concurrent adapter worker did not start")
        release.set()
        for _ in workers:
            try:
                outcome, value = outcomes.get(timeout=2)
            except Empty as exc:
                raise AssertionError("concurrent adapter worker did not finish") from exc
            if outcome == "error":
                errors.append(str(value))
            else:
                results.append(value)
    finally:
        release.set()
        for process in processes:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
    if errors:
        raise AssertionError(f"concurrent adapter worker failed: {errors}")
    if any(process.exitcode not in (0, None) for process in processes):
        raise AssertionError("concurrent adapter worker exited unexpectedly")
    return results


class _FailingMarkerJsonUsageRepository(JsonUsageRepository):
    def save_result(self, user_id: str, operation_id: str, result: dict) -> dict:
        if result.get("state") == "dispatching":
            raise OSError("durable dispatch marker unavailable")
        return super().save_result(user_id, operation_id, result)


class _PausingJsonUsageRepository(JsonUsageRepository):
    """Pause one real protected read while a second adapter contends for its lock."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.read_paused = threading.Event()
        self.resume_read = threading.Event()
        self._pause_next_read = False

    def pause_on_next_read(self) -> None:
        self.read_paused.clear()
        self.resume_read.clear()
        self._pause_next_read = True

    def _load_items_with_cleanup(self) -> list[dict]:
        items = super()._load_items_with_cleanup()
        if self._pause_next_read:
            self._pause_next_read = False
            self.read_paused.set()
            if not self.resume_read.wait(timeout=2):
                raise TimeoutError("test did not resume the protected repository read")
        return items


def _run_paused_interleaving(
    paused_adapter: _PausingJsonUsageRepository,
    owner: Callable[[], object],
    contender: Callable[[], object],
) -> tuple[object | None, object | None, Exception | None, Exception | None]:
    """Exercise a real JSON lock handoff with bounded cleanup for each temp path."""
    paused_adapter.pause_on_next_read()
    contender_started = threading.Event()
    contender_finished = threading.Event()
    owner_result: object | None = None
    contender_result: object | None = None
    owner_error: Exception | None = None
    contender_error: Exception | None = None

    def run_owner() -> None:
        nonlocal owner_result, owner_error
        try:
            owner_result = owner()
        except Exception as exc:
            owner_error = exc

    def run_contender() -> None:
        nonlocal contender_result, contender_error
        contender_started.set()
        try:
            contender_result = contender()
        except Exception as exc:
            contender_error = exc
        finally:
            contender_finished.set()

    owner_thread = threading.Thread(target=run_owner, daemon=True)
    contender_thread = threading.Thread(target=run_contender, daemon=True)
    owner_thread.start()
    if not paused_adapter.read_paused.wait(timeout=2):
        paused_adapter.resume_read.set()
        owner_thread.join(timeout=2)
        raise AssertionError("owner did not pause under the repository lock")
    contender_thread.start()
    try:
        if not contender_started.wait(timeout=2):
            raise AssertionError("lock contender did not start")
        if contender_finished.wait(timeout=0.1):
            raise AssertionError("lock contender finished before the protected read resumed")
    finally:
        paused_adapter.resume_read.set()
        owner_thread.join(timeout=2)
        contender_thread.join(timeout=2)
    if owner_thread.is_alive() or contender_thread.is_alive():
        raise AssertionError("JSON lock interleaving worker did not terminate")
    return owner_result, contender_result, owner_error, contender_error


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
        with mock.patch.dict("os.environ", {"SYNC_RESULT_TTL_SECONDS": "1"}):
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
                        "email": "private@example.test",
                        "article_text": "Article text must stay in the TTL record.",
                        "provider_token": "provider-access-token",
                    },
                },
            )
        records = json.loads(self.path.read_text())
        result_record = next(
            record for record in records if record.get("record_type") == "usage_result"
        )
        result_record["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        write_json_list(self.path, records)
        self.assertIsNone(self.repository.get_result(request.user_id, request.operation_id))
        first_adapter = JsonUsageRepository(self.path)
        second_adapter = JsonUsageRepository(self.path)
        reclaimed = _run_bounded_workers(
            lambda: first_adapter.reclaim_expired(request.user_id, NOW),
            lambda: second_adapter.reclaim_expired(request.user_id, NOW),
        )

        operation = self.repository.get_operation(request.user_id, request.operation_id)
        month = self.repository.get_month(request.user_id, request.month)
        evidence = _operation_record(json.loads(self.path.read_text()), request.operation_id)
        self.assertEqual(sum(reclaimed), 1)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, 17)
        self.assertEqual(month["committed_cost_micro_usd"], 17)
        self.assertEqual(month["tokens"], 5)
        self.assertEqual(evidence["dispatch_evidence_state"], "settled")
        self.assertEqual(
            evidence["dispatch_usage"],
            {
                "actual_cost_micro_usd": 17,
                "input_tokens": 3,
                "output_tokens": 2,
                "total_tokens": 5,
            },
        )
        serialized_evidence = json.dumps(evidence, sort_keys=True)
        for private_value in (
            _PRIVATE_RESPONSE,
            "private@example.test",
            "Article text must stay in the TTL record.",
            "provider-access-token",
        ):
            self.assertNotIn(private_value, serialized_evidence)

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

    def test_completion_and_reclaim_preserve_each_controlled_winner_outcome(self) -> None:
        completed_first = reservation(
            "019b63f8-f600-7000-8000-000000000309",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        reclaimed_first = reservation(
            "019b63f8-f600-7000-8000-000000000315",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(completed_first)
        self.repository.save_result(
            completed_first.user_id,
            completed_first.operation_id,
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": completed_first.cost_micro_usd},
            },
        )
        completion_adapter = _PausingJsonUsageRepository(self.path)
        completion_contender = JsonUsageRepository(self.path)
        _, completion_reclaim_count, completion_error, completion_reclaim_error = (
            _run_paused_interleaving(
                completion_adapter,
                lambda: completion_adapter.save_result(
                    completed_first.user_id,
                    completed_first.operation_id,
                    {
                        "kind": "chat",
                        "state": "completed",
                        "response": {"reply": _PRIVATE_RESPONSE},
                        "usage": {"actual_cost_micro_usd": 17},
                    },
                ),
                lambda: completion_contender.reclaim_expired(_USER_ID, NOW),
            )
        )
        self.assertIsNone(completion_error)
        self.assertIsNone(completion_reclaim_error)
        self.assertEqual(completion_reclaim_count, 1)

        self.repository.reserve(reclaimed_first)
        self.repository.save_result(
            reclaimed_first.user_id,
            reclaimed_first.operation_id,
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": reclaimed_first.cost_micro_usd},
            },
        )
        reclaim_adapter = _PausingJsonUsageRepository(self.path)
        late_completion_adapter = JsonUsageRepository(self.path)
        reclaim_count, _, reclaim_error, late_completion_error = _run_paused_interleaving(
            reclaim_adapter,
            lambda: reclaim_adapter.reclaim_expired(_USER_ID, NOW),
            lambda: late_completion_adapter.save_result(
                reclaimed_first.user_id,
                reclaimed_first.operation_id,
                {
                    "kind": "chat",
                    "state": "completed",
                    "response": {"reply": _PRIVATE_RESPONSE},
                    "usage": {"actual_cost_micro_usd": 17},
                },
            ),
        )
        self.assertIsNone(reclaim_error)
        self.assertEqual(reclaim_count, 1)
        self.assertIsInstance(late_completion_error, UsageOperationStateError)

        completed = self.repository.get_operation(_USER_ID, completed_first.operation_id)
        reclaimed = self.repository.get_operation(_USER_ID, reclaimed_first.operation_id)
        month = self.repository.get_month(_USER_ID, completed_first.month)
        self.assertEqual(completed.state, "finalized")
        self.assertEqual(completed.dispatch_evidence_state, "settled")
        self.assertEqual(completed.actual_cost_micro_usd, 17)
        self.assertEqual(reclaimed.state, "finalized")
        self.assertEqual(reclaimed.dispatch_evidence_state, "settled")
        self.assertEqual(reclaimed.actual_cost_micro_usd, reclaimed_first.cost_micro_usd)
        self.assertEqual(month["committed_cost_micro_usd"], 30)
        self.assertEqual(month["reserved_cost_micro_usd"], 0)

        operation_after_late_completion = self.repository.get_operation(
            _USER_ID,
            reclaimed_first.operation_id,
        )
        self.assertEqual(
            operation_after_late_completion.actual_cost_micro_usd,
            reclaimed_first.cost_micro_usd,
        )

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
        self.assertEqual(settled.input_tokens, 3)
        self.assertEqual(settled.tokens, 3)
        month = self.repository.get_month(request.user_id, request.month)
        self.assertEqual(month["tokens"], 3)
        finalized_event = next(
            record
            for record in json.loads(self.path.read_text())
            if record.get("record_type") == "usage_event"
            and record.get("operation_id") == request.operation_id
            and record.get("transition") == "finalize"
        )
        self.assertEqual(finalized_event["input_tokens"], 3)
        self.assertEqual(finalized_event["tokens"], 3)

    def test_incomplete_usage_evidence_keeps_the_known_cost_and_tokens_monotonic(self) -> None:
        request = reservation(
            "019b63f8-f600-7000-8000-000000000318",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        self.repository.reserve(request)
        for usage in (
            {
                "actual_cost_micro_usd": 17,
                "input_tokens": 3,
                "usage_complete": False,
            },
            {
                "actual_cost_micro_usd": 23,
                "input_tokens": 5,
                "usage_complete": False,
            },
            {
                "actual_cost_micro_usd": 19,
                "input_tokens": 4,
                "total_tokens": 4,
                "usage_complete": True,
            },
        ):
            self.repository.save_result(
                request.user_id,
                request.operation_id,
                {"kind": "preload", "state": "completed", "usage": usage},
            )
            records = json.loads(self.path.read_text())
            result_record = next(
                record for record in records if record.get("record_type") == "usage_result"
            )
            result_record["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            write_json_list(self.path, records)
            self.assertIsNone(self.repository.get_result(request.user_id, request.operation_id))

        self.assertEqual(self.repository.reclaim_expired(request.user_id, NOW), 1)

        settled = self.repository.get_operation(request.user_id, request.operation_id)
        month = self.repository.get_month(request.user_id, request.month)
        finalized_event = next(
            record
            for record in json.loads(self.path.read_text())
            if record.get("record_type") == "usage_event"
            and record.get("operation_id") == request.operation_id
            and record.get("transition") == "finalize"
        )
        self.assertEqual(settled.dispatch_usage_completeness, "conservative")
        self.assertEqual(settled.actual_cost_micro_usd, 23)
        self.assertEqual(settled.input_tokens, 5)
        self.assertEqual(settled.tokens, 5)
        self.assertEqual(month["committed_cost_micro_usd"], 23)
        self.assertEqual(month["tokens"], 5)
        self.assertEqual(finalized_event["actual_cost_micro_usd"], 23)
        self.assertEqual(finalized_event["input_tokens"], 5)
        self.assertEqual(finalized_event["tokens"], 5)

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

    def test_reclaim_and_dispatch_promotion_preserve_each_controlled_winner_outcome(self) -> None:
        promoted_first = reservation(
            "019b63f8-f600-7000-8000-000000000311",
            cost_micro_usd=13,
            expires_at=NOW,
        )
        reclaimed_first = reservation(
            "019b63f8-f600-7000-8000-000000000316",
            cost_micro_usd=13,
            expires_at=NOW,
        )

        self.repository.reserve(promoted_first)
        promotion_adapter = _PausingJsonUsageRepository(self.path)
        promotion_contender = JsonUsageRepository(self.path)
        _, promoted_reclaim_count, promotion_error, promoted_reclaim_error = (
            _run_paused_interleaving(
                promotion_adapter,
                lambda: promotion_adapter.save_result(
                    promoted_first.user_id,
                    promoted_first.operation_id,
                    {
                        "kind": "chat",
                        "state": "dispatching",
                        "usage": {"actual_cost_micro_usd": promoted_first.cost_micro_usd},
                    },
                ),
                lambda: promotion_contender.reclaim_expired(_USER_ID, NOW),
            )
        )
        self.assertIsNone(promotion_error)
        self.assertIsNone(promoted_reclaim_error)
        self.assertEqual(promoted_reclaim_count, 1)

        promoted = self.repository.get_operation(_USER_ID, promoted_first.operation_id)
        self.assertEqual(promoted.state, "finalized")
        self.assertEqual(promoted.actual_cost_micro_usd, promoted_first.cost_micro_usd)
        self.assertEqual(promoted.dispatch_evidence_state, "settled")

        self.repository.reserve(reclaimed_first)
        reclaim_adapter = _PausingJsonUsageRepository(self.path)
        late_promotion_adapter = JsonUsageRepository(self.path)
        reclaimed_count, _, reclaim_error, late_promotion_error = _run_paused_interleaving(
            reclaim_adapter,
            lambda: reclaim_adapter.reclaim_expired(_USER_ID, NOW),
            lambda: late_promotion_adapter.save_result(
                reclaimed_first.user_id,
                reclaimed_first.operation_id,
                {
                    "kind": "chat",
                    "state": "dispatching",
                    "usage": {"actual_cost_micro_usd": reclaimed_first.cost_micro_usd},
                },
            ),
        )
        self.assertIsNone(reclaim_error)
        self.assertEqual(reclaimed_count, 1)
        self.assertIsInstance(late_promotion_error, UsageOperationStateError)

        reclaimed = self.repository.get_operation(_USER_ID, reclaimed_first.operation_id)
        month = self.repository.get_month(_USER_ID, reclaimed_first.month)
        self.assertEqual(reclaimed.state, "released")
        self.assertEqual(reclaimed.dispatch_evidence_state, "not_dispatched")
        self.assertEqual(month["reserved_cost_micro_usd"], 0)


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
        reclaimed = [
            first_adapter.reclaim_expired(request.user_id, NOW),
            second_adapter.reclaim_expired(request.user_id, NOW),
        ]

        operation = first_adapter.get_operation(request.user_id, request.operation_id)
        month = first_adapter.get_month(request.user_id, request.month)
        evidence = json.loads(
            store.items[(user_pk(request.user_id), usage_operation_sk(request.operation_id))][
                DOCUMENT_ATTRIBUTE
            ]
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

    def test_active_provider_claim_blocks_duplicate_without_early_settlement(self) -> None:
        directory = Path(self._temporary_directory.name)
        meter = UsageMeter(
            JsonSubscriptionRepository(directory / "active-subscriptions.json"),
            JsonUsageRepository(directory / "active-usage.json"),
            _USER_ID,
            rate=_RATE,
            now=datetime.now(UTC),
            plan_loader=lambda _plan_id: _PLAN,
            reservation_enabled=True,
        )
        operation = meter.reserve(
            "019b63f8-f600-7000-8000-000000000317",
            "active-provider-claim",
            "chat",
            11,
        )
        provider_started = threading.Event()
        allow_provider_completion = threading.Event()
        owner_errors: list[Exception] = []
        owner_provider = mock.Mock(return_value="owner response")

        def run_owner() -> None:
            tally = UsageTally(rate=_RATE)

            def dispatch() -> str:
                tally.mark_dispatch_attempt()
                provider_started.set()
                if not allow_provider_completion.wait(timeout=2):
                    raise TimeoutError("test did not release the active provider")
                return owner_provider()

            try:
                with SynchronousExecution(
                    meter,
                    operation,
                    kind="chat",
                    response_model=ChatResponse,
                ) as execution:
                    execution.run(tally, dispatch, lambda reply: ChatResponse(reply=reply))
            except Exception as exc:
                owner_errors.append(exc)

        owner = threading.Thread(target=run_owner, daemon=True)
        owner.start()
        self.assertTrue(provider_started.wait(timeout=2))
        duplicate_provider = mock.Mock()
        try:
            with mock.patch.dict("os.environ", {"SYNC_EXECUTION_WAIT_SECONDS": "0.1"}):
                duplicate = SynchronousExecution(
                    meter,
                    meter.get_operation(operation.operation_id),
                    kind="chat",
                    response_model=ChatResponse,
                )
                with self.assertRaises(PipelineError) as context:
                    with duplicate:
                        duplicate.run(
                            UsageTally(rate=_RATE),
                            duplicate_provider,
                            lambda reply: ChatResponse(reply=reply),
                        )
            self.assertEqual(context.exception.status_code, 409)
            duplicate_provider.assert_not_called()
            active = meter.get_operation(operation.operation_id)
            self.assertEqual(active.state, "reserved")
            self.assertEqual(active.dispatch_evidence_state, "dispatched")
        finally:
            allow_provider_completion.set()
            owner.join(timeout=2)
        self.assertFalse(owner.is_alive())
        self.assertEqual(owner_errors, [])
        settled = meter.get_operation(operation.operation_id)
        self.assertEqual(settled.state, "finalized")
        self.assertEqual(owner_provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
