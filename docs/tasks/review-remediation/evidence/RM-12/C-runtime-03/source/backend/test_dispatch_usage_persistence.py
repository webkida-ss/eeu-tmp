"""Parity regressions for canonical numeric dispatch-usage promotion."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from repositories.dynamodb_billing_repositories import DynamoUsageRepository
from repositories.usage_repository import (
    JsonUsageRepository,
    UsageOperationConflict,
    UsageOperationNotFound,
    UsageOperationStateError,
)
from storage.json_list_store import read_json_list
from test_usage_repository import NOW, _MemoryDynamoStore, reservation

_USER_ID = "0190f4c0-0000-7000-8000-000000000001"
_PRIVATE_SENTINEL = "private provider response must never be durable evidence"
_NUMERIC_USAGE = {
    "actual_cost_micro_usd": 17,
    "input_tokens": 17,
    "output_tokens": 0,
    "total_tokens": 17,
}
_COMPLETE_USAGE = {**_NUMERIC_USAGE, "usage_complete": True}


class DispatchUsagePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _repositories(self) -> list[tuple[str, Any, Path | None]]:
        path = Path(self._temporary_directory.name) / "usage.json"
        return [
            ("json", JsonUsageRepository(path), path),
            ("dynamo", DynamoUsageRepository(_MemoryDynamoStore()), None),
        ]

    @staticmethod
    def _shadow_request(operation_id: str, *, expires_at=NOW):
        return replace(
            reservation(
                operation_id,
                articles=1,
                cost_micro_usd=13,
                expires_at=expires_at,
            ),
            accounting_mode="shadow",
            pricing_available=True,
        )

    @staticmethod
    def _numeric_usage_with_private_fields() -> dict[str, Any]:
        return {
            **_COMPLETE_USAGE,
            "response": {"reply": _PRIVATE_SENTINEL},
            "private_result": _PRIVATE_SENTINEL,
            "model": "untrusted-provider-model",
        }

    def test_canonical_numeric_promotion_survives_reclaim_without_ttl_result(self) -> None:
        for name, repository, path in self._repositories():
            with self.subTest(adapter=name):
                request = self._shadow_request(f"dispatch-usage-promote-{name}")
                repository.start_shadow(request)

                promoted = repository.record_dispatch_usage(
                    request.user_id,
                    request.operation_id,
                    "preload",
                    self._numeric_usage_with_private_fields(),
                )

                self.assertEqual(promoted.state, "reserved")
                self.assertEqual(promoted.dispatch_evidence_state, "completed")
                self.assertEqual(promoted.dispatch_kind, "preload")
                self.assertEqual(promoted.dispatch_usage_completeness, "measured")
                self.assertEqual(promoted.dispatch_usage, _NUMERIC_USAGE)
                self.assertIsNone(repository.get_result(request.user_id, request.operation_id))
                self.assertNotIn(_PRIVATE_SENTINEL, json.dumps(asdict(promoted), sort_keys=True))
                self.assertEqual(
                    repository.record_dispatch_usage(
                        request.user_id,
                        request.operation_id,
                        "preload",
                        _NUMERIC_USAGE,
                    ),
                    promoted,
                )
                with self.assertRaises((UsageOperationConflict, UsageOperationStateError)):
                    repository.record_dispatch_usage(
                        request.user_id,
                        request.operation_id,
                        "chat",
                        _NUMERIC_USAGE,
                    )
                with self.assertRaises((UsageOperationConflict, UsageOperationStateError)):
                    repository.record_dispatch_usage(
                        request.user_id,
                        request.operation_id,
                        "preload",
                        {**_NUMERIC_USAGE, "actual_cost_micro_usd": 18},
                    )
                if path is not None:
                    serialized = json.dumps(read_json_list(path), sort_keys=True)
                    self.assertNotIn(_PRIVATE_SENTINEL, serialized)

                reclaimed = repository.reclaim_expired(
                    request.user_id,
                    NOW + timedelta(seconds=1),
                )
                finalized = repository.get_operation(request.user_id, request.operation_id)
                month = repository.get_month(request.user_id, request.month)
                self.assertEqual(reclaimed, 1)
                self.assertEqual(finalized.state, "finalized")
                self.assertEqual(finalized.actual_cost_micro_usd, 17)
                self.assertEqual(finalized.tokens, 17)
                self.assertEqual(finalized.shadow_outcome, "failed_after_dispatch")
                self.assertEqual(month["shadow_cost_micro_usd"], 17)
                self.assertEqual(month["tokens"], 17)
                self.assertEqual(month["articles"], 0)

    def test_canonical_promotion_rejects_missing_prepared_and_settled_winners(self) -> None:
        for name, repository, _path in self._repositories():
            with self.subTest(adapter=name, state="missing"):
                with self.assertRaises(UsageOperationNotFound):
                    repository.record_dispatch_usage(
                        _USER_ID,
                        f"missing-dispatch-usage-{name}",
                        "preload",
                        _NUMERIC_USAGE,
                    )

            with self.subTest(adapter=name, state="prepared"):
                prepared_request = self._shadow_request(
                    f"dispatch-usage-prepared-{name}",
                    expires_at=NOW + timedelta(days=1),
                )
                repository.start_shadow(prepared_request)
                repository.record_dispatch_usage(
                    prepared_request.user_id,
                    prepared_request.operation_id,
                    "preload",
                    _NUMERIC_USAGE,
                )
                repository.prepare_shadow_settlement(
                    prepared_request.user_id,
                    prepared_request.operation_id,
                    "failed_after_dispatch",
                )
                with self.assertRaises((UsageOperationConflict, UsageOperationStateError)):
                    repository.record_dispatch_usage(
                        prepared_request.user_id,
                        prepared_request.operation_id,
                        "preload",
                        _NUMERIC_USAGE,
                    )

            with self.subTest(adapter=name, state="reclaimed"):
                request = self._shadow_request(f"dispatch-usage-reclaim-{name}")
                repository.start_shadow(request)
                repository.save_result(
                    request.user_id,
                    request.operation_id,
                    {
                        "kind": "preload",
                        "state": "dispatching",
                        "usage": {"actual_cost_micro_usd": 13},
                    },
                )
                self.assertEqual(
                    repository.reclaim_expired(request.user_id, NOW + timedelta(seconds=1)),
                    1,
                )
                winner = repository.get_operation(request.user_id, request.operation_id)
                with self.assertRaises((UsageOperationConflict, UsageOperationStateError)):
                    repository.record_dispatch_usage(
                        request.user_id,
                        request.operation_id,
                        "preload",
                        _NUMERIC_USAGE,
                    )
                current = repository.get_operation(request.user_id, request.operation_id)
                self.assertEqual(current, winner)
                self.assertEqual(current.actual_cost_micro_usd, 13)
                self.assertEqual(current.tokens, 0)
                self.assertEqual(current.shadow_outcome, "failed_after_dispatch")


if __name__ == "__main__":
    unittest.main()
