from __future__ import annotations

import json
import multiprocessing
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from repositories.dynamodb_billing_repositories import DynamoUsageRepository
from repositories.usage_repository import (
    JsonUsageRepository,
    UsageFinalizeRequest,
    UsageOperation,
    UsageOperationConflict,
    UsageQuotaExceeded,
    UsageReservationRequest,
)
from storage.dynamodb_keys import (
    usage_event_sk,
    usage_result_sk,
    usage_sk,
    user_pk,
)
from storage.dynamodb_store import DOCUMENT_ATTRIBUTE, DynamoDbStore
from storage.json_list_store import write_json_list

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _json_add_worker(path: str, iterations: int) -> None:
    repository = JsonUsageRepository(Path(path))
    for _ in range(iterations):
        repository.add("cross-process-user", "2026-07", articles=1)


def reservation(
    operation_id: str,
    *,
    payload_hash: str = "payload-a",
    articles: int = 0,
    chats: int = 0,
    cost_micro_usd: int = 0,
    article_limit: int = 10,
    chat_limit: int = 10,
    cost_limit: int = 1_000,
    sentence_limit: int = 50,
    source_token_limit: int = 12_000,
    tokenizer_encoding: str = "encoding-v1",
    plan_id: str = "basic",
    expires_at: datetime | None = None,
) -> UsageReservationRequest:
    return UsageReservationRequest(
        operation_id=operation_id,
        user_id="0190f4c0-0000-7000-8000-000000000001",
        month="2026-07",
        meter="article" if articles else "chat" if chats else "cost",
        payload_hash=payload_hash,
        plan_id=plan_id,
        rate_card_version="2026-07",
        articles=articles,
        chats=chats,
        cost_micro_usd=cost_micro_usd,
        article_limit=article_limit,
        chat_limit=chat_limit,
        cost_micro_usd_limit=cost_limit,
        sentences_per_article=sentence_limit,
        source_tokens_per_article=source_token_limit,
        tokenizer_encoding=tokenizer_encoding,
        model="test-model",
        input_micro_usd_per_million=10,
        output_micro_usd_per_million=20,
        expires_at=expires_at or NOW + timedelta(minutes=10),
    )


class UsageOperationTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = reservation(
            "operation-transition",
            articles=1,
            cost_micro_usd=75,
            article_limit=12,
            chat_limit=34,
            cost_limit=5_678,
            sentence_limit=90,
            source_token_limit=12_345,
        )
        self.reserved_fields = {
            "operation_id": "operation-transition",
            "user_id": "0190f4c0-0000-7000-8000-000000000001",
            "month": "2026-07",
            "meter": "article",
            "payload_hash": "payload-a",
            "plan_id": "basic",
            "rate_card_version": "2026-07",
            "article_limit": 12,
            "chat_limit": 34,
            "cost_micro_usd_limit": 5_678,
            "sentences_per_article": 90,
            "source_tokens_per_article": 12_345,
            "model": "test-model",
            "input_micro_usd_per_million": 10,
            "output_micro_usd_per_million": 20,
            "reserved_articles": 1,
            "reserved_chats": 0,
            "reserved_cost_micro_usd": 75,
            "state": "reserved",
            "expires_at": NOW + timedelta(minutes=10),
            "tokenizer_encoding": "encoding-v1",
            "result_ref": None,
            "actual_articles": 0,
            "actual_chats": 0,
            "actual_cost_micro_usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tokens": 0,
            "release_reason": None,
            "dispatch_evidence_state": "unknown",
            "dispatch_evidence_version": 0,
            "dispatch_kind": None,
            "dispatch_usage_completeness": "unknown",
            "dispatch_usage": None,
        }

    def test_reserved_factory_preserves_every_request_field(self) -> None:
        self.assertEqual(
            asdict(UsageOperation.reserved(self.request)),
            {
                **self.reserved_fields,
                "dispatch_evidence_state": "not_dispatched",
                "dispatch_evidence_version": 1,
            },
        )

    def test_finalized_transition_changes_only_settlement_fields(self) -> None:
        operation = UsageOperation(**self.reserved_fields)
        request = UsageFinalizeRequest(
            user_id=operation.user_id,
            operation_id=operation.operation_id,
            actual_cost_micro_usd=91,
            input_tokens=7,
            output_tokens=11,
            tokens=18,
            result_ref="usage-result:operation-transition",
        )

        finalized = operation.finalized(request, actual_tokens=18)

        self.assertEqual(
            asdict(finalized),
            {
                **self.reserved_fields,
                "state": "finalized",
                "result_ref": "usage-result:operation-transition",
                "actual_articles": 1,
                "actual_chats": 0,
                "actual_cost_micro_usd": 91,
                "input_tokens": 7,
                "output_tokens": 11,
                "tokens": 18,
                "dispatch_evidence_state": "settled",
                "dispatch_evidence_version": 1,
                "dispatch_usage_completeness": "measured",
                "dispatch_usage": {
                    "actual_cost_micro_usd": 91,
                    "input_tokens": 7,
                    "output_tokens": 11,
                    "total_tokens": 18,
                },
            },
        )

    def test_released_transition_changes_only_release_fields(self) -> None:
        operation = UsageOperation(**self.reserved_fields)

        released = operation.released("provider_failed")

        self.assertEqual(
            asdict(released),
            {
                **self.reserved_fields,
                "state": "released",
                "release_reason": "provider_failed",
                "dispatch_evidence_version": 1,
            },
        )

    def test_renewed_transition_changes_only_expiry(self) -> None:
        operation = UsageOperation(**self.reserved_fields)
        renewed_expiry = NOW + timedelta(hours=1)

        renewed = operation.renewed(renewed_expiry)

        self.assertEqual(
            asdict(renewed),
            {
                **self.reserved_fields,
                "expires_at": renewed_expiry,
                "dispatch_evidence_version": 1,
            },
        )


class JsonUsageLifecycleTests(unittest.TestCase):
    def test_crash_boundary_markers_finalize_instead_of_release(self) -> None:
        for index, state in enumerate(("dispatching", "completed")):
            request = reservation(
                f"json-crash-{index}",
                cost_micro_usd=13,
                expires_at=NOW - timedelta(seconds=1),
            )
            self.repository.reserve(request)
            self.repository.save_result(
                self.user_id,
                request.operation_id,
                {
                    "kind": "preload",
                    "state": state,
                    "usage": {"actual_cost_micro_usd": 13},
                },
            )

        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 2)
        for index in range(2):
            operation = self.repository.get_operation(self.user_id, f"json-crash-{index}")
            self.assertEqual(operation.state, "finalized")
            self.assertEqual(operation.actual_cost_micro_usd, 13)

    def test_finalize_commits_incurred_overage_and_blocks_future_reserve(self) -> None:
        request = reservation(
            "overage-finalize",
            cost_micro_usd=80,
            cost_limit=100,
        )
        self.repository.reserve(request)

        finalized = self.repository.finalize(
            UsageFinalizeRequest(
                self.user_id,
                request.operation_id,
                actual_cost_micro_usd=150,
            )
        )

        self.assertEqual(finalized.actual_cost_micro_usd, 150)
        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["reserved_cost_micro_usd"], 0)
        self.assertEqual(month["committed_cost_micro_usd"], 150)
        with self.assertRaises(UsageQuotaExceeded):
            self.repository.reserve(
                reservation(
                    "after-overage",
                    cost_micro_usd=1,
                    cost_limit=100,
                )
            )
        events = json.loads(self.path.read_text())
        finalized_event = next(
            event
            for event in events
            if event.get("transition") == "finalize"
            and event.get("operation_id") == request.operation_id
        )
        self.assertEqual(finalized_event["overage_cost_micro_usd"], 70)

    def test_reclaim_accepts_production_cost_snapshot_key(self) -> None:
        request = reservation(
            "production-snapshot",
            cost_micro_usd=10,
            expires_at=NOW - timedelta(seconds=1),
        )
        self.repository.reserve(request)
        self.repository.save_result(
            self.user_id,
            request.operation_id,
            {
                "kind": "preload",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "cost_micro_usd": 77,
                },
            },
        )

        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 1)
        operation = self.repository.get_operation(self.user_id, request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, 77)

    def test_reclaim_isolates_malformed_result_and_continues(self) -> None:
        malformed = reservation(
            "malformed-result",
            cost_micro_usd=9,
            expires_at=NOW - timedelta(seconds=1),
        )
        unrelated = reservation(
            "unrelated-expired",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        self.repository.reserve(malformed)
        self.repository.reserve(unrelated)
        self.repository.save_result(
            self.user_id,
            malformed.operation_id,
            {"kind": "preload", "usage": {"cost_micro_usd": "bad"}},
        )

        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 2)
        self.assertEqual(
            self.repository.get_operation(self.user_id, malformed.operation_id).state,
            "finalized",
        )
        self.assertEqual(
            self.repository.get_operation(
                self.user_id, malformed.operation_id
            ).actual_cost_micro_usd,
            malformed.cost_micro_usd,
        )
        self.assertEqual(
            self.repository.get_operation(self.user_id, unrelated.operation_id).state,
            "released",
        )

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "usage.json"
        self.repository = JsonUsageRepository(self.path)
        self.user_id = "0190f4c0-0000-7000-8000-000000000001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_tokenizer_encoding_is_persisted_in_operation_and_audit_event(self) -> None:
        request = reservation("tokenizer-audit", cost_micro_usd=1)
        operation = self.repository.reserve(request)

        self.assertEqual(operation.tokenizer_encoding, "encoding-v1")
        records = json.loads(self.path.read_text())
        event = next(
            item
            for item in records
            if item.get("record_type") == "usage_event"
            and item.get("operation_id") == request.operation_id
        )
        self.assertEqual(event["tokenizer_encoding"], "encoding-v1")

    def test_pending_result_is_durable_and_idempotent(self) -> None:
        result = {
            "kind": "chat",
            "response": {"reply": "saved"},
            "usage": {"actual_cost_micro_usd": 7},
        }

        self.repository.save_result(self.user_id, "operation-1", result)
        self.repository.save_result(self.user_id, "operation-1", result)

        self.assertEqual(self.repository.get_result(self.user_id, "operation-1"), result)

    def test_expired_pending_result_is_reconciled_without_leaking_reservation(self) -> None:
        request = reservation(
            "operation-with-result",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        self.repository.reserve(request)
        self.repository.save_result(
            self.user_id,
            request.operation_id,
            {"kind": "chat", "response": {"reply": "saved"}, "usage": {}},
        )

        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 1)
        self.assertEqual(
            self.repository.get_operation(self.user_id, request.operation_id).state,
            "finalized",
        )
        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["reserved_chats"], 0)
        self.assertEqual(month["committed_chats"], 1)

    def test_execution_claim_is_exclusive_and_recoverable_after_expiry(self) -> None:
        first_expiry = NOW + timedelta(seconds=5)
        self.assertEqual(
            self.repository.claim_execution(
                self.user_id, "operation-1", "claim-1", NOW, first_expiry
            ),
            "claimed",
        )
        self.assertFalse(
            self.repository.claim_execution(
                self.user_id,
                "operation-1",
                "claim-2",
                NOW + timedelta(seconds=1),
                NOW + timedelta(seconds=6),
            )
        )
        self.assertFalse(
            self.repository.renew_execution(
                self.user_id,
                "operation-1",
                "wrong-claim",
                NOW + timedelta(seconds=7),
            )
        )
        self.assertTrue(
            self.repository.renew_execution(
                self.user_id,
                "operation-1",
                "claim-1",
                NOW + timedelta(seconds=7),
            )
        )
        self.assertEqual(
            self.repository.claim_execution(
                self.user_id,
                "operation-1",
                "claim-2",
                NOW + timedelta(seconds=8),
                NOW + timedelta(seconds=11),
            ),
            "recovered",
        )

    def test_active_execution_claim_prevents_reservation_reclaim(self) -> None:
        request = reservation(
            "active-execution",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        self.repository.reserve(request)
        self.assertTrue(
            self.repository.claim_execution(
                self.user_id,
                request.operation_id,
                "claim-1",
                NOW,
                NOW + timedelta(seconds=30),
            )
        )

        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 0)
        self.assertEqual(
            self.repository.get_operation(self.user_id, request.operation_id).state,
            "reserved",
        )

    def test_result_record_has_expiry_and_lazy_cleanup(self) -> None:
        result = {
            "kind": "chat",
            "response": {"reply": "saved"},
            "usage": {"actual_cost_micro_usd": 1},
        }
        self.repository.save_result(self.user_id, "expiring-result", result)
        items = json.loads(self.path.read_text())
        stored = next(item for item in items if item.get("record_type") == "usage_result")
        self.assertIn("expires_at", stored)
        stored["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        write_json_list(self.path, items)

        self.assertIsNone(self.repository.get_result(self.user_id, "expiring-result"))
        remaining = json.loads(self.path.read_text())
        self.assertFalse(any(item.get("record_type") == "usage_result" for item in remaining))

    def test_unrelated_repository_operations_sweep_expired_results_in_batches(self) -> None:
        for index in range(3):
            self.repository.save_result(
                self.user_id,
                f"expired-{index}",
                {
                    "kind": "chat",
                    "response": {"reply": str(index)},
                    "usage": {"actual_cost_micro_usd": 1},
                },
            )
        items = json.loads(self.path.read_text())
        for item in items:
            if item.get("record_type") == "usage_result":
                item["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        write_json_list(self.path, items)

        with patch.dict("os.environ", {"SYNC_RESULT_CLEANUP_BATCH_SIZE": "2"}):
            self.repository.get_month(self.user_id, "2026-07")
            after_first = json.loads(self.path.read_text())
            self.assertEqual(
                sum(item.get("record_type") == "usage_result" for item in after_first),
                1,
            )
            self.repository.get_month(self.user_id, "2026-07")

        after_second = json.loads(self.path.read_text())
        self.assertFalse(any(item.get("record_type") == "usage_result" for item in after_second))

    def test_result_record_enforces_serialized_size_ceiling(self) -> None:
        with (
            patch.dict("os.environ", {"SYNC_RESULT_MAX_BYTES": "100"}),
            self.assertRaisesRegex(Exception, "size ceiling"),
        ):
            self.repository.save_result(
                self.user_id,
                "oversized-result",
                {
                    "kind": "chat",
                    "response": {"reply": "x" * 500},
                    "usage": {},
                },
            )

    def test_dispatch_marker_transitions_to_completed_result(self) -> None:
        self.repository.save_result(
            self.user_id,
            "dispatch-transition",
            {
                "kind": "chat",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": 10},
            },
        )
        completed = {
            "kind": "chat",
            "state": "completed",
            "response": {"reply": "saved"},
            "usage": {"actual_cost_micro_usd": 7},
        }
        self.repository.save_result(self.user_id, "dispatch-transition", completed)
        self.assertEqual(
            self.repository.get_result(self.user_id, "dispatch-transition"),
            completed,
        )

    def test_one_remaining_slot_is_atomic_under_parallel_callers(self) -> None:
        self.repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000010",
                articles=1,
                article_limit=2,
            )
        )
        barrier = threading.Barrier(3)
        outcomes: list[str] = []

        def reserve_last(operation_id: str) -> None:
            barrier.wait()
            try:
                self.repository.reserve(reservation(operation_id, articles=1, article_limit=2))
                outcomes.append("reserved")
            except UsageQuotaExceeded:
                outcomes.append("blocked")

        callers = [
            threading.Thread(
                target=reserve_last,
                args=(f"0190f4c0-0000-7000-8000-00000000002{i}",),
            )
            for i in range(2)
        ]
        for caller in callers:
            caller.start()
        barrier.wait()
        for caller in callers:
            caller.join()

        self.assertCountEqual(outcomes, ["reserved", "blocked"])
        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["reserved_articles"], 2)

    def test_same_id_replays_but_different_payload_conflicts(self) -> None:
        request = reservation("0190f4c0-0000-7000-8000-000000000030", articles=1)
        first = self.repository.reserve(request)
        replay = self.repository.reserve(request)
        self.assertEqual(replay, first)
        self.assertEqual(
            self.repository.get_month(self.user_id, "2026-07")["reserved_articles"],
            1,
        )

        with self.assertRaises(UsageOperationConflict):
            self.repository.reserve(
                reservation(
                    request.operation_id,
                    payload_hash="different",
                    articles=1,
                )
            )

    def test_finalize_and_release_are_idempotent_and_nonnegative(self) -> None:
        finalized = reservation(
            "0190f4c0-0000-7000-8000-000000000040",
            articles=1,
            cost_micro_usd=100,
        )
        self.repository.reserve(finalized)
        request = UsageFinalizeRequest(
            user_id=self.user_id,
            operation_id=finalized.operation_id,
            input_tokens=20,
            output_tokens=5,
            actual_cost_micro_usd=80,
            result_ref="article-1",
        )
        first = self.repository.finalize(request)
        self.assertEqual(self.repository.finalize(request), first)

        released = reservation("0190f4c0-0000-7000-8000-000000000041", chats=1)
        self.repository.reserve(released)
        first_release = self.repository.release(
            self.user_id, released.operation_id, reason="provider_failed"
        )
        self.assertEqual(
            self.repository.release(self.user_id, released.operation_id, reason="provider_failed"),
            first_release,
        )

        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["committed_articles"], 1)
        self.assertEqual(month["committed_cost_micro_usd"], 80)
        self.assertEqual(month["reserved_articles"], 0)
        self.assertEqual(month["reserved_chats"], 0)
        self.assertEqual(month["reserved_cost_micro_usd"], 0)

        records = json.loads(self.path.read_text(encoding="utf-8"))
        finalize_event = next(
            record
            for record in records
            if record.get("record_type") == "usage_event" and record.get("transition") == "finalize"
        )
        self.assertEqual(finalize_event["rate_card_version"], "2026-07")
        self.assertEqual(finalize_event["model"], "test-model")
        self.assertEqual(finalize_event["input_tokens"], 20)
        self.assertEqual(finalize_event["output_tokens"], 5)
        self.assertEqual(finalize_event["tokens"], 25)
        self.assertEqual(finalize_event["actual_cost_micro_usd"], 80)

    def test_finalize_actual_over_estimate_commits_atomically(self) -> None:
        request = reservation(
            "0190f4c0-0000-7000-8000-000000000050",
            cost_micro_usd=80,
            cost_limit=100,
        )
        self.repository.reserve(request)
        self.repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000051",
                cost_micro_usd=20,
                cost_limit=100,
            )
        )
        self.repository.finalize(
            UsageFinalizeRequest(
                user_id=self.user_id,
                operation_id=request.operation_id,
                actual_cost_micro_usd=81,
            )
        )

        operation = self.repository.get_operation(self.user_id, request.operation_id)
        self.assertIsNotNone(operation)
        self.assertEqual(operation.state, "finalized")
        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["reserved_cost_micro_usd"], 20)
        self.assertEqual(month["committed_cost_micro_usd"], 81)

    def test_reclaim_expired_releases_once_and_appends_transition_events(self) -> None:
        expired = reservation(
            "0190f4c0-0000-7000-8000-000000000060",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        active = reservation(
            "0190f4c0-0000-7000-8000-000000000061",
            chats=1,
        )
        self.repository.reserve(expired)
        self.repository.reserve(active)
        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 1)
        self.assertEqual(self.repository.reclaim_expired(self.user_id, NOW), 0)

        records = json.loads(self.path.read_text(encoding="utf-8"))
        events = [record for record in records if record.get("record_type") == "usage_event"]
        self.assertEqual(
            [(event["operation_id"], event["transition"]) for event in events],
            [
                (expired.operation_id, "reserve"),
                (active.operation_id, "reserve"),
                (expired.operation_id, "release"),
            ],
        )

    def test_snapshot_limits_only_ratchet_upward(self) -> None:
        self.repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000070",
                articles=1,
                article_limit=2,
                cost_limit=100,
                sentence_limit=50,
                source_token_limit=12_000,
                plan_id="basic",
            )
        )
        self.repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000071",
                chats=1,
                article_limit=1,
                chat_limit=5,
                cost_limit=90,
                sentence_limit=40,
                source_token_limit=10_000,
                plan_id="basic",
            )
        )
        self.repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000072",
                chats=1,
                article_limit=20,
                chat_limit=20,
                cost_limit=2_000,
                sentence_limit=200,
                source_token_limit=48_000,
                plan_id="pro",
            )
        )

        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["article_limit"], 20)
        self.assertEqual(month["chat_limit"], 20)
        self.assertEqual(month["cost_micro_usd_limit"], 2_000)
        self.assertEqual(month["sentences_per_article"], 200)
        self.assertEqual(month["source_tokens_per_article"], 48_000)
        self.assertEqual(month["plan_id"], "pro")

        operation = self.repository.get_operation(
            self.user_id, "0190f4c0-0000-7000-8000-000000000072"
        )
        self.assertEqual(operation.sentences_per_article, 200)
        self.assertEqual(operation.source_tokens_per_article, 48_000)

    def test_first_snapshot_migrates_legacy_usage_exactly_once(self) -> None:
        self.path.write_text(
            json.dumps(
                [
                    {
                        "user_id": self.user_id,
                        "month": "2026-07",
                        "articles": 2,
                        "chats": 3,
                        "tokens": 400,
                    }
                ]
            ),
            encoding="utf-8",
        )
        request = reservation(
            "0190f4c0-0000-7000-8000-000000000073",
            articles=1,
            article_limit=3,
        )

        self.repository.reserve(request)
        self.repository.reserve(request)
        finalize = UsageFinalizeRequest(
            user_id=self.user_id,
            operation_id=request.operation_id,
            input_tokens=10,
            output_tokens=5,
        )
        self.repository.finalize(finalize)
        self.repository.finalize(finalize)

        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["committed_articles"], 3)
        self.assertEqual(month["committed_chats"], 3)
        self.assertEqual(month["tokens"], 415)
        self.assertEqual(month["reserved_articles"], 0)
        with self.assertRaises(UsageQuotaExceeded):
            self.repository.reserve(
                reservation(
                    "0190f4c0-0000-7000-8000-000000000074",
                    articles=1,
                    article_limit=3,
                )
            )

    def test_snapshot_reconciles_usage_recorded_during_shadow_rollback(self) -> None:
        self.repository.add(self.user_id, "2026-07", articles=1)
        first = reservation(
            "0190f4c0-0000-7000-8000-000000000075",
            articles=1,
            article_limit=3,
        )
        self.repository.reserve(first)
        self.repository.finalize(
            UsageFinalizeRequest(
                user_id=self.user_id,
                operation_id=first.operation_id,
            )
        )

        self.repository.add(self.user_id, "2026-07", articles=1)

        month = self.repository.get_month(self.user_id, "2026-07")
        self.assertEqual(month["articles"], 3)
        self.assertEqual(month["committed_articles"], 3)
        with self.assertRaises(UsageQuotaExceeded):
            self.repository.reserve(
                reservation(
                    "0190f4c0-0000-7000-8000-000000000076",
                    articles=1,
                    article_limit=3,
                )
            )

    def test_first_snapshot_enforces_cost_recorded_in_shadow_mode(self) -> None:
        self.repository.add(
            self.user_id,
            "2026-07",
            shadow_cost_micro_usd=40,
        )

        with self.assertRaises(UsageQuotaExceeded) as raised:
            self.repository.reserve(
                reservation(
                    "0190f4c0-0000-7000-8000-000000000077",
                    cost_micro_usd=61,
                    cost_limit=100,
                )
            )

        self.assertEqual(raised.exception.meter, "cost")

    def test_old_rows_default_new_counters_without_migrating_raw_values(self) -> None:
        self.path.write_text(
            json.dumps(
                [
                    {
                        "user_id": self.user_id,
                        "month": "2026-06",
                        "articles": 3,
                        "chats": 4,
                        "tokens": 5,
                    }
                ]
            ),
            encoding="utf-8",
        )
        month = self.repository.get_month(self.user_id, "2026-06")
        self.assertEqual(month["articles"], 3)
        self.assertEqual(month["chats"], 4)
        self.assertEqual(month["tokens"], 5)
        self.assertEqual(month["committed_articles"], 0)
        self.assertEqual(month["reserved_chats"], 0)
        self.assertEqual(month["committed_cost_micro_usd"], 0)

    def test_add_rejects_non_integer_or_negative_amounts_without_mutation(self) -> None:
        invalid_amounts = (-1, True, "1", 1.5)
        for amount in invalid_amounts:
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.repository.add(self.user_id, "2026-07", articles=amount)
        self.assertEqual(self.repository.get_month(self.user_id, "2026-07")["articles"], 0)

    def test_cross_process_adds_do_not_lose_updates(self) -> None:
        process_count = 4
        iterations = 20
        context = multiprocessing.get_context("spawn")
        processes = [
            context.Process(
                target=_json_add_worker,
                args=(str(self.path), iterations),
            )
            for _ in range(process_count)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
            self.assertEqual(process.exitcode, 0)

        month = self.repository.get_month("cross-process-user", "2026-07")
        self.assertEqual(month["articles"], process_count * iterations)

    def test_atomic_writer_fsyncs_and_replaces_target(self) -> None:
        with (
            patch("storage.json_list_store.os.fsync") as fsync,
            patch(
                "storage.json_list_store.os.replace",
                wraps=__import__("os").replace,
            ) as replace,
        ):
            write_json_list(self.path, [{"value": 1}])

        self.assertTrue(fsync.called)
        replace.assert_called_once()
        source, target = replace.call_args.args
        self.assertEqual(Path(target), self.path)
        self.assertNotEqual(Path(source), self.path)
        self.assertEqual(json.loads(self.path.read_text()), [{"value": 1}])


class _RecordingStore:
    table_name = "usage-table"

    def __init__(self) -> None:
        self.transactions: list[list[dict]] = []

    def get_item(self, _pk: str, _sk: str, *, consistent_read: bool = False):
        return None

    def get_document(self, _pk: str, _sk: str):
        return None

    def transact_write(self, items: list[dict]) -> None:
        self.transactions.append(items)

    def query_by_pk(self, _pk: str, *, sk_prefix: str | None = None):
        return []


_DESERIALIZER = TypeDeserializer()


def _transaction_cancelled() -> ClientError:
    return ClientError(
        {
            "Error": {
                "Code": "TransactionCanceledException",
                "Message": "conditional conflict",
            },
            "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
        },
        "TransactWriteItems",
    )


class _MemoryDynamoStore:
    table_name = "usage-table"

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}
        self.transactions: list[list[dict]] = []
        self.consistent_reads: list[bool] = []
        self.failures_remaining = 0
        self.failure_exception: ClientError | None = None
        self.on_failure = None
        self.query_barrier: threading.Barrier | None = None
        self._lock = threading.RLock()

    def get_item(self, pk: str, sk: str, *, consistent_read: bool = False):
        with self._lock:
            self.consistent_reads.append(consistent_read)
            return deepcopy(self.items.get((pk, sk)))

    def get_document(self, pk: str, sk: str):
        item = self.get_item(pk, sk, consistent_read=True)
        if not item:
            return None
        raw = item.get("document")
        return json.loads(raw) if isinstance(raw, str) else None

    def delete(self, pk: str, sk: str):
        with self._lock:
            self.items.pop((pk, sk), None)

    def put_document_if_absent(self, pk, sk, document, *, extra_attributes=None):
        with self._lock:
            if (pk, sk) in self.items:
                return False
            self.items[(pk, sk)] = {
                "pk": pk,
                "sk": sk,
                "document": json.dumps(document),
                **(extra_attributes or {}),
            }
            return True

    def conditional_put_document(
        self,
        pk,
        sk,
        document,
        *,
        extra_attributes,
        expected_attributes,
    ):
        with self._lock:
            current = self.items.get((pk, sk))
            if not current or any(
                current.get(key) != value for key, value in expected_attributes.items()
            ):
                return False
            self.items[(pk, sk)] = {
                "pk": pk,
                "sk": sk,
                "document": json.dumps(document),
                **extra_attributes,
            }
            return True

    def transact_write(self, items: list[dict]) -> None:
        with self._lock:
            self.transactions.append(items)
            if self.failures_remaining:
                self.failures_remaining -= 1
                if self.on_failure:
                    self.on_failure()
                raise self.failure_exception or _transaction_cancelled()

            writes: list[tuple[tuple[str, str], dict]] = []
            for entry in items:
                if "ConditionCheck" in entry:
                    check = entry["ConditionCheck"]
                    key_values = {
                        key: _DESERIALIZER.deserialize(value) for key, value in check["Key"].items()
                    }
                    key = (key_values["pk"], key_values["sk"])
                    if not self._condition_matches(
                        check,
                        self.items.get(key),
                        check.get("ConditionExpression"),
                    ):
                        raise _transaction_cancelled()
                    continue
                put = entry["Put"]
                item = {key: _DESERIALIZER.deserialize(value) for key, value in put["Item"].items()}
                key = (item["pk"], item["sk"])
                existing = self.items.get(key)
                condition = put.get("ConditionExpression")
                if not self._condition_matches(put, existing, condition):
                    raise _transaction_cancelled()
                writes.append((key, item))
            for key, item in writes:
                self.items[key] = item

    def query_by_pk(self, pk: str, *, sk_prefix: str | None = None):
        with self._lock:
            documents = [
                json.loads(item["document"])
                for (item_pk, sk), item in self.items.items()
                if item_pk == pk
                and (sk_prefix is None or sk.startswith(sk_prefix))
                and isinstance(item.get("document"), str)
            ]
        if self.query_barrier:
            self.query_barrier.wait()
        return documents

    @staticmethod
    def _condition_matches(put: dict, existing: dict | None, condition: str | None):
        if condition is None:
            return True
        if condition == "attribute_not_exists(pk)":
            return existing is None
        if condition == "attribute_not_exists(#version)":
            return existing is None or "version" not in existing
        values = {
            key: _DESERIALIZER.deserialize(value)
            for key, value in put.get("ExpressionAttributeValues", {}).items()
        }
        if condition == "#version = :expected_version":
            return existing is not None and existing.get("version") == values[":expected_version"]
        if condition == "attribute_not_exists(pk) OR #expires_at <= :now":
            return existing is None or str(existing.get("expires_at") or "") <= values[":now"]
        if condition.startswith("#state = :expected_state"):
            if existing is None or existing.get("state") != values[":expected_state"]:
                return False
            if (
                ":expected_evidence_version" in values
                and existing.get("dispatch_evidence_version")
                != values[":expected_evidence_version"]
            ):
                return False
            if "attribute_not_exists(#evidence_version)" in condition and (
                "dispatch_evidence_version" in existing
            ):
                return False
            if ":expected_expires_at" in values and (
                "expires_at" in existing
                and existing.get("expires_at") != values[":expected_expires_at"]
            ):
                return False
            return True
        raise AssertionError(f"Unexpected condition: {condition}")


class DynamoUsageTransactionTests(unittest.TestCase):
    def test_dynamo_crash_boundary_markers_finalize_instead_of_release(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        for index, state in enumerate(("dispatching", "completed")):
            request = reservation(
                f"dynamo-crash-{index}",
                cost_micro_usd=13,
                expires_at=NOW - timedelta(seconds=1),
            )
            repository.reserve(request)
            repository.save_result(
                request.user_id,
                request.operation_id,
                {
                    "kind": "preload",
                    "state": state,
                    "usage": {"actual_cost_micro_usd": 13},
                },
            )

        self.assertEqual(
            repository.reclaim_expired("0190f4c0-0000-7000-8000-000000000001", NOW),
            2,
        )
        for index in range(2):
            operation = repository.get_operation(
                "0190f4c0-0000-7000-8000-000000000001",
                f"dynamo-crash-{index}",
            )
            self.assertEqual(operation.state, "finalized")
            self.assertEqual(operation.actual_cost_micro_usd, 13)

    def test_dynamo_finalize_commits_incurred_overage_and_blocks_future_reserve(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        request = reservation(
            "dynamo-overage",
            cost_micro_usd=80,
            cost_limit=100,
        )
        repository.reserve(request)

        finalized = repository.finalize(
            UsageFinalizeRequest(
                request.user_id,
                request.operation_id,
                actual_cost_micro_usd=150,
            )
        )

        self.assertEqual(finalized.actual_cost_micro_usd, 150)
        self.assertEqual(
            repository.get_month(request.user_id, request.month)["committed_cost_micro_usd"],
            150,
        )
        with self.assertRaises(UsageQuotaExceeded):
            repository.reserve(
                reservation(
                    "dynamo-after-overage",
                    cost_micro_usd=1,
                    cost_limit=100,
                )
            )

    def test_dynamo_reclaim_uses_production_cost_and_isolates_malformed_result(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        production = reservation(
            "dynamo-production-result",
            cost_micro_usd=10,
            expires_at=NOW - timedelta(seconds=1),
        )
        malformed = reservation(
            "dynamo-malformed-result",
            cost_micro_usd=11,
            expires_at=NOW - timedelta(seconds=1),
        )
        repository.reserve(production)
        repository.reserve(malformed)
        repository.save_result(
            production.user_id,
            production.operation_id,
            {"kind": "preload", "usage": {"cost_micro_usd": 77}},
        )
        repository.save_result(
            malformed.user_id,
            malformed.operation_id,
            {"kind": "preload", "usage": {"cost_micro_usd": "bad"}},
        )

        self.assertEqual(repository.reclaim_expired(production.user_id, NOW), 2)
        self.assertEqual(
            repository.get_operation(
                production.user_id, production.operation_id
            ).actual_cost_micro_usd,
            77,
        )
        self.assertEqual(
            repository.get_operation(
                malformed.user_id, malformed.operation_id
            ).actual_cost_micro_usd,
            malformed.cost_micro_usd,
        )

    def test_dynamo_persists_tokenizer_encoding_in_operation_and_audit(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = reservation("dynamo-tokenizer-audit", cost_micro_usd=1)

        operation = repository.reserve(request)

        self.assertEqual(operation.tokenizer_encoding, "encoding-v1")
        event_item = store.items[
            (user_pk(request.user_id), usage_event_sk(request.operation_id, "reserve"))
        ]
        event = json.loads(event_item[DOCUMENT_ATTRIBUTE])
        self.assertEqual(event["tokenizer_encoding"], "encoding-v1")

    def test_active_dynamo_execution_claim_prevents_reservation_reclaim(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = reservation(
            "active-execution",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        repository.reserve(request)
        repository.claim_execution(
            request.user_id,
            request.operation_id,
            "claim-1",
            NOW,
            NOW + timedelta(seconds=30),
        )

        self.assertEqual(repository.reclaim_expired(request.user_id, NOW), 0)
        self.assertEqual(
            repository.get_operation(request.user_id, request.operation_id).state,
            "reserved",
        )

    def test_dynamo_reclaim_rechecks_expiry_after_renewal_conflict(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = reservation(
            "reclaim-renew-race",
            cost_micro_usd=13,
            expires_at=NOW - timedelta(seconds=1),
        )
        repository.reserve(request)
        repository.save_result(
            request.user_id,
            request.operation_id,
            {"kind": "preload", "state": "dispatching", "usage": {}},
        )
        self.assertEqual(
            repository.claim_execution(
                request.user_id,
                request.operation_id,
                "live-owner",
                NOW - timedelta(seconds=2),
                NOW - timedelta(seconds=1),
            ),
            "claimed",
        )

        store.failures_remaining = 1

        def renew_before_reclaim_retry() -> None:
            repository.renew(
                request.user_id,
                request.operation_id,
                NOW + timedelta(minutes=5),
            )
            self.assertTrue(
                repository.renew_execution(
                    request.user_id,
                    request.operation_id,
                    "live-owner",
                    NOW + timedelta(minutes=5),
                )
            )

        store.on_failure = renew_before_reclaim_retry

        self.assertEqual(repository.reclaim_expired(request.user_id, NOW), 0)
        self.assertEqual(
            repository.get_operation(request.user_id, request.operation_id).state,
            "reserved",
        )

    def test_dynamo_result_enforces_serialized_size_ceiling(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        with (
            patch.dict("os.environ", {"SYNC_RESULT_MAX_BYTES": "100"}),
            self.assertRaisesRegex(Exception, "size ceiling"),
        ):
            repository.save_result(
                "u1",
                "oversized-result",
                {
                    "kind": "analyze",
                    "response": {"translation": "x" * 500},
                    "usage": {},
                },
            )

    def test_dynamo_dispatch_marker_transitions_to_completed_result(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        repository.save_result(
            "u1",
            "dispatch-transition",
            {
                "kind": "analyze",
                "state": "dispatching",
                "usage": {"actual_cost_micro_usd": 10},
            },
        )
        completed = {
            "kind": "analyze",
            "state": "completed",
            "response": {"translation": "saved"},
            "usage": {"actual_cost_micro_usd": 7},
        }
        repository.save_result("u1", "dispatch-transition", completed)
        self.assertEqual(
            repository.get_result("u1", "dispatch-transition"),
            completed,
        )

    def test_dynamo_result_expiry_is_cleaned_lazily(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        repository.save_result(
            "u1",
            "expiring-result",
            {
                "kind": "chat",
                "response": {"reply": "saved"},
                "usage": {"actual_cost_micro_usd": 1},
            },
        )
        key = (user_pk("u1"), usage_result_sk("expiring-result"))
        document = json.loads(store.items[key]["document"])
        document["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        store.items[key]["document"] = json.dumps(document)

        self.assertIsNone(repository.get_result("u1", "expiring-result"))
        self.assertNotIn(key, store.items)

    def test_dynamo_result_has_numeric_epoch_ttl_attribute(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        repository.save_result(
            "u1",
            "ttl-result",
            {
                "kind": "chat",
                "response": {"reply": "saved"},
                "usage": {"actual_cost_micro_usd": 1},
            },
        )

        item = store.items[(user_pk("u1"), usage_result_sk("ttl-result"))]
        self.assertIsInstance(item["expires_at_epoch"], int)
        self.assertGreater(item["expires_at_epoch"], int(NOW.timestamp()))

    def test_execution_claim_is_exclusive_and_reclaims_expired_owner(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        self.assertEqual(
            repository.claim_execution(
                "u1", "operation-1", "claim-1", NOW, NOW + timedelta(seconds=5)
            ),
            "claimed",
        )
        self.assertFalse(
            repository.claim_execution(
                "u1",
                "operation-1",
                "claim-2",
                NOW + timedelta(seconds=1),
                NOW + timedelta(seconds=6),
            )
        )
        self.assertFalse(
            repository.renew_execution(
                "u1",
                "operation-1",
                "wrong-claim",
                NOW + timedelta(seconds=7),
            )
        )
        self.assertTrue(
            repository.renew_execution(
                "u1",
                "operation-1",
                "claim-1",
                NOW + timedelta(seconds=7),
            )
        )
        self.assertEqual(
            repository.claim_execution(
                "u1",
                "operation-1",
                "claim-2",
                NOW + timedelta(seconds=8),
                NOW + timedelta(seconds=11),
            ),
            "recovered",
        )

    def test_expired_dynamo_pending_result_is_finalized(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = reservation(
            "operation-with-result",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        repository.reserve(request)
        # This represents a pre-evidence durable operation with a surviving
        # trusted private result, rather than a new explicit no-dispatch record.
        operation_item = store.items[
            (user_pk(request.user_id), usage_operation_sk(request.operation_id))
        ]
        legacy_operation = json.loads(operation_item[DOCUMENT_ATTRIBUTE])
        for field in (
            "dispatch_evidence_state",
            "dispatch_evidence_version",
            "dispatch_kind",
            "dispatch_usage_completeness",
            "dispatch_usage",
        ):
            legacy_operation.pop(field, None)
            operation_item.pop(field, None)
        operation_item[DOCUMENT_ATTRIBUTE] = json.dumps(legacy_operation)
        store.items[(user_pk(request.user_id), usage_result_sk(request.operation_id))] = {
            "pk": user_pk(request.user_id),
            "sk": usage_result_sk(request.operation_id),
            DOCUMENT_ATTRIBUTE: json.dumps(
                {
                    "kind": "chat",
                    "response": {"reply": "saved"},
                    "usage": {"actual_cost_micro_usd": 3},
                }
            ),
        }

        self.assertEqual(repository.reclaim_expired(request.user_id, NOW), 1)
        operation = repository.get_operation(request.user_id, request.operation_id)
        self.assertEqual(operation.state, "finalized")
        self.assertEqual(operation.actual_cost_micro_usd, 3)

    def test_pending_result_uses_dedicated_dynamo_document(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = replace(reservation("operation-1"), user_id="u1")
        repository.reserve(request)

        repository.save_result(
            "u1",
            "operation-1",
            {"kind": "analyze", "response": {"translation": "saved"}},
        )
        loaded = repository.get_result("u1", "operation-1")

        self.assertEqual(loaded["response"]["translation"], "saved")
        self.assertIn(
            (user_pk("u1"), usage_result_sk("operation-1")),
            store.items,
        )

    def test_reserve_uses_one_conditional_three_item_transaction(self) -> None:
        store = _RecordingStore()
        repository = DynamoUsageRepository(store)
        operation = repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000080",
                articles=1,
                cost_micro_usd=20,
            )
        )

        self.assertEqual(operation.state, "reserved")
        self.assertEqual(len(store.transactions), 1)
        transaction = store.transactions[0]
        self.assertEqual(len(transaction), 3)
        self.assertTrue(
            all("ConditionExpression" in next(iter(item.values())) for item in transaction)
        )

    def test_legacy_migration_is_not_doubled_by_transaction_retry(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        repository.add(
            "0190f4c0-0000-7000-8000-000000000001",
            "2026-07",
            articles=2,
            chats=3,
            tokens=400,
        )
        store.failures_remaining = 1

        operation = repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000081",
                articles=1,
                article_limit=3,
                sentence_limit=77,
                source_token_limit=9_999,
            )
        )

        month = repository.get_month(operation.user_id, operation.month)
        self.assertEqual(month["committed_articles"], 2)
        self.assertEqual(month["committed_chats"], 3)
        self.assertEqual(month["tokens"], 400)
        self.assertEqual(month["reserved_articles"], 1)
        self.assertEqual(operation.sentences_per_article, 77)
        self.assertEqual(operation.source_tokens_per_article, 9_999)

    def test_store_forwards_transact_write_items_to_low_level_client(self) -> None:
        class _Client:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def transact_write_items(self, **kwargs):
                self.calls.append(kwargs)

        client = _Client()
        resource = SimpleNamespace(
            Table=lambda _name: SimpleNamespace(name="usage-table"),
            meta=SimpleNamespace(client=client),
        )
        store = DynamoDbStore(table_name="usage-table", resource=resource)
        transaction = [
            {
                "Put": {
                    "TableName": "usage-table",
                    "Item": {"pk": {"S": "USER#u1"}, "sk": {"S": "USAGE#2026-07"}},
                }
            }
        ]
        store.transact_write(transaction)
        self.assertEqual(client.calls, [{"TransactItems": transaction}])

    def test_store_supports_one_consistent_raw_item_read(self) -> None:
        class _Table:
            name = "usage-table"

            def __init__(self) -> None:
                self.calls: list[dict] = []

            def get_item(self, **kwargs):
                self.calls.append(kwargs)
                return {"Item": {"pk": "USER#u1", "sk": "USAGE#2026-07"}}

        table = _Table()
        resource = SimpleNamespace(
            Table=lambda _name: table,
            meta=SimpleNamespace(client=SimpleNamespace()),
        )
        store = DynamoDbStore(table_name="usage-table", resource=resource)

        item = store.get_item("USER#u1", "USAGE#2026-07", consistent_read=True)

        self.assertEqual(item["pk"], "USER#u1")
        self.assertEqual(
            table.calls,
            [
                {
                    "Key": {"pk": "USER#u1", "sk": "USAGE#2026-07"},
                    "ConsistentRead": True,
                }
            ],
        )

    def test_month_is_loaded_with_one_consistent_item_read(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        repository.get_month("u1", "2026-07")
        self.assertEqual(store.consistent_reads, [True])

    def test_compatibility_add_retries_and_advances_version(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        repository.add("u1", "2026-07", articles=2)
        store.failures_remaining = 1

        month = repository.add("u1", "2026-07", articles=3, tokens=7)

        self.assertEqual(month["articles"], 5)
        self.assertEqual(month["tokens"], 7)
        raw = store.get_item(user_pk("u1"), usage_sk("2026-07"))
        self.assertEqual(raw["version"], 2)
        self.assertEqual(len(store.transactions), 3)

    def test_dynamo_snapshot_reconciles_shadow_rollback_usage(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        request = reservation(
            "0190f4c0-0000-7000-8000-000000000092",
            articles=1,
            article_limit=3,
        )
        repository.add(request.user_id, request.month, articles=1)
        repository.reserve(request)
        repository.finalize(
            UsageFinalizeRequest(
                user_id=request.user_id,
                operation_id=request.operation_id,
            )
        )

        repository.add(request.user_id, request.month, articles=1)

        month = repository.get_month(request.user_id, request.month)
        self.assertEqual(month["articles"], 3)
        self.assertEqual(month["committed_articles"], 3)
        with self.assertRaises(UsageQuotaExceeded):
            repository.reserve(
                reservation(
                    "0190f4c0-0000-7000-8000-000000000093",
                    articles=1,
                    article_limit=3,
                )
            )

    def test_dynamo_first_snapshot_enforces_shadow_cost(self) -> None:
        repository = DynamoUsageRepository(_MemoryDynamoStore())
        request = reservation(
            "0190f4c0-0000-7000-8000-000000000094",
            cost_micro_usd=61,
            cost_limit=100,
        )
        repository.add(
            request.user_id,
            request.month,
            shadow_cost_micro_usd=40,
        )

        with self.assertRaises(UsageQuotaExceeded) as raised:
            repository.reserve(request)

        self.assertEqual(raised.exception.meter, "cost")

    def test_add_rejects_non_integer_or_negative_amounts_without_writes(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        for amount in (-1, True, "1", 1.5):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    repository.add("u1", "2026-07", articles=amount)
        self.assertEqual(store.transactions, [])

    def test_permanent_transaction_cancellation_is_not_retried_or_wrapped(self) -> None:
        store = _MemoryDynamoStore()
        error = ClientError(
            {
                "Error": {
                    "Code": "TransactionCanceledException",
                    "Message": "validation failed",
                },
                "CancellationReasons": [{"Code": "ValidationError", "Message": "bad expression"}],
            },
            "TransactWriteItems",
        )
        store.failures_remaining = 1
        store.failure_exception = error
        repository = DynamoUsageRepository(store)

        with self.assertRaises(ClientError) as context:
            repository.add("u1", "2026-07", articles=1)

        self.assertIs(context.exception, error)
        self.assertEqual(len(store.transactions), 1)

    def test_finalize_release_replays_create_one_event_each(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        finalized_request = reservation(
            "0190f4c0-0000-7000-8000-000000000090",
            articles=1,
            cost_micro_usd=20,
        )
        repository.reserve(finalized_request)
        finalize = UsageFinalizeRequest(
            user_id=finalized_request.user_id,
            operation_id=finalized_request.operation_id,
            actual_cost_micro_usd=15,
        )
        first_finalize = repository.finalize(finalize)
        self.assertEqual(repository.finalize(finalize), first_finalize)

        released_request = reservation("0190f4c0-0000-7000-8000-000000000091", chats=1)
        repository.reserve(released_request)
        first_release = repository.release(
            released_request.user_id,
            released_request.operation_id,
            reason="failed",
        )
        self.assertEqual(
            repository.release(
                released_request.user_id,
                released_request.operation_id,
                reason="failed",
            ),
            first_release,
        )

        transitions = [
            json.loads(item["document"])["transition"]
            for (_pk, sk), item in store.items.items()
            if sk.startswith("USAGE_EVENT#")
        ]
        self.assertCountEqual(transitions, ["reserve", "finalize", "reserve", "release"])
        finalize_events = [
            json.loads(item["document"])
            for (_pk, sk), item in store.items.items()
            if sk.startswith("USAGE_EVENT#") and sk.endswith("#finalize")
        ]
        self.assertEqual(len(finalize_events), 1)
        self.assertEqual(finalize_events[0]["rate_card_version"], "2026-07")
        self.assertEqual(finalize_events[0]["model"], "test-model")
        self.assertEqual(finalize_events[0]["input_tokens"], 0)
        self.assertEqual(finalize_events[0]["output_tokens"], 0)
        self.assertEqual(finalize_events[0]["tokens"], 0)
        self.assertEqual(finalize_events[0]["actual_cost_micro_usd"], 15)
        transition_transactions = (store.transactions[1], store.transactions[3])
        self.assertTrue(
            all(
                len(transaction) == 3
                and all(
                    "ConditionExpression" in next(iter(entry.values())) for entry in transaction
                )
                for transaction in transition_transactions
            )
        )

    def test_conditional_retry_keeps_event_unique(self) -> None:
        store = _MemoryDynamoStore()
        store.failures_remaining = 1
        repository = DynamoUsageRepository(store)
        request = reservation("0190f4c0-0000-7000-8000-000000000092", articles=1)
        repository.reserve(request)
        repository.reserve(request)

        events = [
            sk
            for (_pk, sk) in store.items
            if sk.startswith("USAGE_EVENT#") and sk.endswith("#reserve")
        ]
        self.assertEqual(len(store.transactions), 2)
        self.assertEqual(len(events), 1)
        with self.assertRaises(UsageOperationConflict):
            repository.reserve(
                reservation(
                    request.operation_id,
                    payload_hash="different",
                    articles=1,
                )
            )

    def test_concurrent_same_id_replays_and_conflicts_stably(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = reservation("0190f4c0-0000-7000-8000-000000000096", articles=1)
        barrier = threading.Barrier(3)
        operations = []

        def replay() -> None:
            barrier.wait()
            operations.append(repository.reserve(request))

        callers = [threading.Thread(target=replay) for _ in range(2)]
        for caller in callers:
            caller.start()
        barrier.wait()
        for caller in callers:
            caller.join()

        self.assertEqual(operations, [operations[0], operations[0]])
        reserve_events = [
            sk
            for (_pk, sk) in store.items
            if sk.startswith("USAGE_EVENT#") and sk.endswith("#reserve")
        ]
        self.assertEqual(len(reserve_events), 1)

        conflicts: list[str] = []

        def conflict() -> None:
            try:
                repository.reserve(
                    reservation(
                        request.operation_id,
                        payload_hash="different",
                        articles=1,
                    )
                )
            except UsageOperationConflict:
                conflicts.append("conflict")

        conflict_callers = [threading.Thread(target=conflict) for _ in range(2)]
        for caller in conflict_callers:
            caller.start()
        for caller in conflict_callers:
            caller.join()
        self.assertEqual(conflicts, ["conflict", "conflict"])

    def test_quota_after_conditional_retry_maps_to_stable_exception(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        repository.reserve(
            reservation(
                "0190f4c0-0000-7000-8000-000000000093",
                articles=1,
                article_limit=2,
            )
        )
        store.failures_remaining = 1

        def consume_last_slot() -> None:
            key = (
                user_pk("0190f4c0-0000-7000-8000-000000000001"),
                usage_sk("2026-07"),
            )
            item = store.items[key]
            document = json.loads(item["document"])
            document["reserved_articles"] = 2
            item["reserved_articles"] = 2
            item["version"] += 1
            item["document"] = json.dumps(document)

        store.on_failure = consume_last_slot
        with self.assertRaises(UsageQuotaExceeded) as context:
            repository.reserve(
                reservation(
                    "0190f4c0-0000-7000-8000-000000000094",
                    articles=1,
                    article_limit=2,
                )
            )
        self.assertEqual(context.exception.meter, "article")

    def test_concurrent_reclaim_counts_only_transaction_winner(self) -> None:
        store = _MemoryDynamoStore()
        repository = DynamoUsageRepository(store)
        request = reservation(
            "0190f4c0-0000-7000-8000-000000000095",
            chats=1,
            expires_at=NOW - timedelta(seconds=1),
        )
        repository.reserve(request)
        store.query_barrier = threading.Barrier(2)
        results: list[int] = []

        callers = [
            threading.Thread(
                target=lambda: results.append(repository.reclaim_expired(request.user_id, NOW))
            )
            for _ in range(2)
        ]
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join()

        self.assertCountEqual(results, [0, 1])
        release_events = [
            sk
            for (_pk, sk) in store.items
            if sk.startswith("USAGE_EVENT#") and sk.endswith("#release")
        ]
        self.assertEqual(len(release_events), 1)


if __name__ == "__main__":
    unittest.main()
