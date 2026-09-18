from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from core.pipeline import UsageSnapshot, UsageTally
from core.usage_costs import ModelRate
from repositories.admin_activity import ActivityEvent, AdminActivityRepository
from repositories.json_admin_activity import JsonAdminActivityRepository
from repositories.memory_admin_activity import MemoryAdminActivityRepository
from services.admin_activity import TerminalActivityOutcome, record_terminal_activity
from services.entitlements import EntitlementError

_USER_ID = "019b63f8-f600-7000-8000-000000000101"
_SECOND_USER_ID = "019b63f8-f600-7000-8000-000000000102"
_OPERATION_ID = "019b63f8-f600-7000-8000-000000000201"
_PRELOAD_ID = "019b63f8-f600-7000-8000-000000000301"


class _FailingRepository:
    def append(self, event: ActivityEvent) -> ActivityEvent:
        raise RuntimeError("activity storage unavailable")


class _RaisingSnapshotTally:
    provider_model = "provider-fallback"
    input_tokens = 3
    output_tokens = 4
    total_tokens = 7

    def snapshot(self) -> object:
        raise RuntimeError("snapshot unavailable")


class _TransientSnapshotTally:
    input_tokens = 1
    output_tokens = 2
    total_tokens = 3
    provider_model = "fallback-model"

    def __init__(self) -> None:
        self.snapshot_calls = 0

    def snapshot(self) -> UsageSnapshot:
        self.snapshot_calls += 1
        if self.snapshot_calls == 1:
            raise RuntimeError("transient snapshot failure")
        return UsageSnapshot(
            model="rate-model",
            provider_model="provider-model",
            rate_card_version="rate-v1",
            input_tokens=10,
            output_tokens=11,
            total_tokens=21,
            cost_micro_usd=22,
            missing_usage=False,
        )


def _outcome(**kwargs: object) -> TerminalActivityOutcome:
    values: dict[str, object] = {
        "operation": "chat",
        "operation_id": _OPERATION_ID,
        "user_id": _USER_ID,
        "status": "success",
    }
    values.update(kwargs)
    return TerminalActivityOutcome(**values)  # type: ignore[arg-type]


class TerminalActivityOutcomeTests(unittest.TestCase):
    def test_source_id_preserves_operation_id_and_status_exactly(self) -> None:
        outcome = _outcome(
            operation="article", operation_id="preload/with:identity", status="failed"
        )

        self.assertEqual(outcome.source_id, "article:preload/with:identity:failed")

    def test_for_preload_preserves_legacy_usage_and_model_selection(self) -> None:
        error = EntitlementError(
            "quota reached",
            code="article_quota_exceeded",
            status_code=402,
        )
        outcome = TerminalActivityOutcome.for_preload(
            _USER_ID,
            _PRELOAD_ID,
            "quota_blocked",
            error=error,
            record={
                "usage_tally": {"input_tokens": 1},
                "failure_usage": {"input_tokens": 2},
                "model": "record-model",
            },
        )

        self.assertEqual(outcome.operation, "article")
        self.assertEqual(outcome.operation_id, _PRELOAD_ID)
        self.assertEqual(outcome.error, error)
        self.assertEqual(outcome.usage, {"input_tokens": 1})
        self.assertEqual(outcome.model, "record-model")


class RecordTerminalActivityTests(unittest.TestCase):
    def test_missing_tally_keeps_activity_usage_fields_null(self) -> None:
        repository = MemoryAdminActivityRepository()

        record_terminal_activity(repository, _outcome(tally=None))

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertIsNone(event.input_tokens)
        self.assertIsNone(event.output_tokens)
        self.assertIsNone(event.tokens)
        self.assertIsNone(event.actual_cost_micro_usd)

    def test_zero_usage_is_distinct_from_missing_tally(self) -> None:
        repository = MemoryAdminActivityRepository()
        tally = UsageTally(rate=ModelRate("provider-model", 1, 1, "test-v1"))
        tally.add_response(
            mock.Mock(
                model="provider-model",
                usage=mock.Mock(
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                ),
            )
        )

        record_terminal_activity(repository, _outcome(tally=tally))

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertEqual(event.input_tokens, 0)
        self.assertEqual(event.output_tokens, 0)
        self.assertEqual(event.tokens, 0)
        self.assertEqual(event.actual_cost_micro_usd, 0)
        self.assertEqual(event.model, "provider-model")

    def test_usage_override_preserves_zero_and_none_values(self) -> None:
        repository = MemoryAdminActivityRepository()
        tally = mock.Mock()
        tally.snapshot.return_value = mock.Mock(
            input_tokens=10,
            output_tokens=11,
            total_tokens=21,
            actual_cost_micro_usd=22,
            provider_model="tally-model",
        )

        record_terminal_activity(
            repository,
            _outcome(
                tally=tally,
                usage={
                    "input_tokens": 0,
                    "output_tokens": None,
                    "total_tokens": 0,
                    "actual_cost_micro_usd": None,
                    "provider_model": "usage-provider-model",
                },
                model="explicit-model",
            ),
        )

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertEqual(event.input_tokens, 0)
        self.assertIsNone(event.output_tokens)
        self.assertEqual(event.tokens, 0)
        self.assertIsNone(event.actual_cost_micro_usd)
        self.assertEqual(event.model, "explicit-model")

    def test_transient_snapshot_failure_retries_before_using_counter_fallback(self) -> None:
        repository = MemoryAdminActivityRepository()
        tally = _TransientSnapshotTally()

        record_terminal_activity(repository, _outcome(tally=tally))

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertEqual(tally.snapshot_calls, 2)
        self.assertEqual(event.input_tokens, 10)
        self.assertEqual(event.output_tokens, 11)
        self.assertEqual(event.tokens, 21)
        self.assertEqual(event.actual_cost_micro_usd, 22)
        self.assertEqual(event.model, "fallback-model")

    def test_snapshot_failure_uses_counter_fields_and_provider_model(self) -> None:
        repository = MemoryAdminActivityRepository()

        record_terminal_activity(repository, _outcome(tally=_RaisingSnapshotTally()))

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertEqual(event.input_tokens, 3)
        self.assertEqual(event.output_tokens, 4)
        self.assertEqual(event.tokens, 7)
        self.assertIsNone(event.actual_cost_micro_usd)
        self.assertEqual(event.model, "provider-fallback")

    def test_error_code_and_model_are_sanitized_by_activity_service(self) -> None:
        repository = MemoryAdminActivityRepository()
        error = EntitlementError("private detail", code="quota / exceeded", status_code=402)

        record_terminal_activity(
            repository,
            _outcome(
                status="quota_blocked",
                error=error,
                model="vendor/model<script>",
            ),
        )

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertEqual(event.error_code, "quota_/_exceeded")
        self.assertEqual(event.model, "vendor/model_script")
        self.assertNotIn("private", repr(event))

    def test_generic_error_uses_exception_type_as_error_code(self) -> None:
        repository = MemoryAdminActivityRepository()

        record_terminal_activity(
            repository, _outcome(error=ValueError("private detail"), status="failed")
        )

        event = repository.query(
            user_id=_USER_ID,
            start=datetime.min.replace(tzinfo=UTC),
            end=datetime.max.replace(tzinfo=UTC),
        )[0]
        self.assertEqual(event.error_code, "ValueError")

    def test_missing_repository_is_a_no_op(self) -> None:
        record_terminal_activity(None, _outcome())

    def test_failure_recording_propagates_by_default(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "activity storage unavailable"):
            record_terminal_activity(_FailingRepository(), _outcome())  # type: ignore[arg-type]

    def test_failure_recording_is_suppressed_only_when_requested(self) -> None:
        with mock.patch("services.admin_activity.logger.exception") as log_exception:
            record_terminal_activity(
                _FailingRepository(),
                _outcome(),
                preserve_failure=True,
            )  # type: ignore[arg-type]

        log_exception.assert_called_once()

    def test_terminal_activity_replay_is_scoped_to_the_account_for_memory_and_json(self) -> None:
        with TemporaryDirectory() as directory:
            repositories: list[AdminActivityRepository] = [
                MemoryAdminActivityRepository(),
                JsonAdminActivityRepository(Path(directory) / "activity.json"),
            ]
            for repository in repositories:
                with self.subTest(repository=type(repository).__name__):
                    first = _outcome(operation_id=_OPERATION_ID, user_id=_USER_ID)
                    replay = _outcome(
                        operation_id=_OPERATION_ID,
                        user_id=_USER_ID,
                        status="success",
                        error=ValueError("later error"),
                    )
                    other_account = _outcome(
                        operation_id=_OPERATION_ID,
                        user_id=_SECOND_USER_ID,
                        status="success",
                    )
                    record_terminal_activity(repository, first)
                    record_terminal_activity(repository, replay)
                    record_terminal_activity(repository, other_account)

                    events = repository.query(
                        user_id=_USER_ID,
                        start=datetime.min.replace(tzinfo=UTC),
                        end=datetime.max.replace(tzinfo=UTC),
                    )
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0].status, "success")
                    self.assertIsNone(events[0].error_code)
                    other_events = repository.query(
                        user_id=_SECOND_USER_ID,
                        start=datetime.min.replace(tzinfo=UTC),
                        end=datetime.max.replace(tzinfo=UTC),
                    )
                    self.assertEqual(len(other_events), 1)
                    self.assertEqual(other_events[0].source_id, other_account.source_id)
                    self.assertEqual(other_events[0].user_id, _SECOND_USER_ID)
                    self.assertEqual(other_events[0].status, "success")

    def test_quota_blocked_terminal_activity_is_scoped_to_the_account(self) -> None:
        with TemporaryDirectory() as directory:
            repositories: list[AdminActivityRepository] = [
                MemoryAdminActivityRepository(),
                JsonAdminActivityRepository(Path(directory) / "activity.json"),
            ]
            for repository in repositories:
                with self.subTest(repository=type(repository).__name__):
                    first = _outcome(operation="article", status="quota_blocked")
                    same_account_replay = _outcome(
                        operation="article",
                        status="quota_blocked",
                        error=ValueError("later error"),
                    )
                    second = _outcome(
                        operation="article",
                        user_id=_SECOND_USER_ID,
                        status="quota_blocked",
                    )

                    record_terminal_activity(repository, first, preserve_failure=True)
                    record_terminal_activity(repository, same_account_replay, preserve_failure=True)
                    record_terminal_activity(repository, second, preserve_failure=True)

                    for user_id in (_USER_ID, _SECOND_USER_ID):
                        events = repository.query(
                            user_id=user_id,
                            start=datetime.min.replace(tzinfo=UTC),
                            end=datetime.max.replace(tzinfo=UTC),
                        )
                        self.assertEqual(len(events), 1)
                        self.assertEqual(events[0].status, "quota_blocked")
                    self.assertIsNone(
                        repository.query(
                            user_id=_USER_ID,
                            start=datetime.min.replace(tzinfo=UTC),
                            end=datetime.max.replace(tzinfo=UTC),
                        )[0].error_code
                    )


if __name__ == "__main__":
    unittest.main()
