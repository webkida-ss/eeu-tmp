from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from repositories.admin_activity import ActivityEvent
from repositories.json_admin_activity import JsonAdminActivityRepository
from repositories.memory_admin_activity import MemoryAdminActivityRepository


def _event(
    *,
    event_id: str = "0198-activity",
    source_id: str = "source-1",
    user_id: str = "user-1",
    operation: str = "article",
    status: str = "success",
    recorded_at: datetime = datetime(2026, 7, 19, 10, tzinfo=UTC),
    error_code: str | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        id=event_id,
        source_id=source_id,
        user_id=user_id,
        operation=operation,
        status=status,
        recorded_at=recorded_at,
        error_code=error_code,
        input_tokens=10,
        output_tokens=5,
        tokens=15,
        actual_cost_micro_usd=21,
        model="test-model",
    )


class AdminActivityRepositoryContract:
    def create_repository(self):
        raise NotImplementedError

    def test_append_is_idempotent_by_account_and_source_id(self) -> None:
        repository = self.create_repository()
        original = _event()
        replacement = _event(
            event_id="different-id",
            status="failed",
        )

        self.assertEqual(repository.append(original), original)
        self.assertEqual(repository.append(replacement), original)
        self.assertEqual(
            repository.query(
                user_id="user-1",
                start=datetime(2026, 7, 19, tzinfo=UTC),
                end=datetime(2026, 7, 20, tzinfo=UTC),
            ),
            [original],
        )

    def test_append_isolated_by_account_for_the_same_source_id(self) -> None:
        repository = self.create_repository()
        first = _event(event_id="first", user_id="user-1")
        second = _event(event_id="second", user_id="user-2")

        self.assertEqual(repository.append(first), first)
        self.assertEqual(repository.append(second), second)
        self.assertEqual(
            repository.query(
                user_id="user-1",
                start=datetime(2026, 7, 19, tzinfo=UTC),
                end=datetime(2026, 7, 20, tzinfo=UTC),
            ),
            [first],
        )
        self.assertEqual(
            repository.query(
                user_id="user-2",
                start=datetime(2026, 7, 19, tzinfo=UTC),
                end=datetime(2026, 7, 20, tzinfo=UTC),
            ),
            [second],
        )

    def test_query_filters_user_time_operation_and_status(self) -> None:
        repository = self.create_repository()
        start = datetime(2026, 7, 19, 10, tzinfo=UTC)
        included = _event(recorded_at=start, operation="chat", status="failed")
        repository.append(included)
        repository.append(
            _event(
                event_id="before",
                source_id="source-before",
                recorded_at=start - timedelta(microseconds=1),
            )
        )
        repository.append(
            _event(
                event_id="end",
                source_id="source-end",
                recorded_at=start + timedelta(hours=1),
                operation="chat",
                status="failed",
            )
        )
        repository.append(
            _event(
                event_id="other-user",
                source_id="source-user",
                user_id="user-2",
                recorded_at=start,
                operation="chat",
                status="failed",
            )
        )

        result = repository.query(
            user_id="user-1",
            start=start,
            end=start + timedelta(hours=1),
            operation="chat",
            status="failed",
        )

        self.assertEqual(result, [included])

    def test_query_orders_deterministically_by_recorded_at_and_id(self) -> None:
        repository = self.create_repository()
        timestamp = datetime(2026, 7, 19, 10, tzinfo=UTC)
        later = _event(
            event_id="c",
            source_id="source-c",
            recorded_at=timestamp + timedelta(seconds=1),
        )
        second = _event(event_id="b", source_id="source-b", recorded_at=timestamp)
        first = _event(event_id="a", source_id="source-a", recorded_at=timestamp)
        for event in (later, second, first):
            repository.append(event)

        result = repository.query(
            user_id="user-1",
            start=timestamp,
            end=timestamp + timedelta(minutes=1),
        )

        self.assertEqual([event.id for event in result], ["a", "b", "c"])


class MemoryAdminActivityRepositoryTests(AdminActivityRepositoryContract, unittest.TestCase):
    def create_repository(self):
        return MemoryAdminActivityRepository()


class JsonAdminActivityRepositoryTests(AdminActivityRepositoryContract, unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tempdir.name) / "admin_activity.json"

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def create_repository(self):
        return JsonAdminActivityRepository(self.path)

    def test_serializes_utc_iso_and_normalizes_offsets_on_read(self) -> None:
        repository = self.create_repository()
        offset = timezone(timedelta(hours=9))
        event = _event(recorded_at=datetime(2026, 7, 19, 19, tzinfo=offset))

        repository.append(event)

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw[0]["recorded_at"], "2026-07-19T10:00:00+00:00")
        raw[0]["recorded_at"] = "2026-07-19T19:00:00+09:00"
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = repository.query(
            user_id="user-1",
            start=datetime(2026, 7, 19, 9, tzinfo=UTC),
            end=datetime(2026, 7, 19, 11, tzinfo=UTC),
        )
        self.assertEqual(loaded[0].recorded_at, datetime(2026, 7, 19, 10, tzinfo=UTC))

    def test_rejects_invalid_persisted_event(self) -> None:
        self.path.write_text(
            json.dumps(
                [
                    {
                        "id": "event",
                        "source_id": "source",
                        "user_id": "user",
                        "operation": "unexpected",
                        "status": "success",
                        "recorded_at": "2026-07-19T10:00:00+00:00",
                    }
                ]
            ),
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            self.create_repository().query(
                user_id="user",
                start=datetime(2026, 7, 19, tzinfo=UTC),
                end=datetime(2026, 7, 20, tzinfo=UTC),
            )

    def test_reopened_legacy_events_are_deduplicated_per_account(self) -> None:
        legacy = _event(event_id="legacy", source_id="legacy-source", user_id="user-1")
        self.path.write_text(
            json.dumps(
                [
                    {
                        "id": legacy.id,
                        "source_id": legacy.source_id,
                        "user_id": legacy.user_id,
                        "operation": legacy.operation,
                        "status": legacy.status,
                        "recorded_at": legacy.recorded_at.isoformat(),
                        "error_code": legacy.error_code,
                        "input_tokens": legacy.input_tokens,
                        "output_tokens": legacy.output_tokens,
                        "tokens": legacy.tokens,
                        "actual_cost_micro_usd": legacy.actual_cost_micro_usd,
                        "model": legacy.model,
                    }
                ]
            ),
            encoding="utf-8",
        )

        reopened = JsonAdminActivityRepository(self.path)
        self.assertEqual(
            reopened.append(_event(event_id="replay", source_id="legacy-source")), legacy
        )
        second = _event(event_id="second", source_id="legacy-source", user_id="user-2")
        self.assertEqual(reopened.append(second), second)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))), 2)

    def test_concurrent_duplicate_append_persists_one_record(self) -> None:
        barrier = threading.Barrier(2)
        results: list[ActivityEvent] = []

        def append(event: ActivityEvent) -> None:
            repository = JsonAdminActivityRepository(self.path)
            barrier.wait()
            results.append(repository.append(event))

        first = _event(event_id="a")
        second = _event(event_id="b")
        threads = [
            threading.Thread(target=append, args=(first,)),
            threading.Thread(target=append, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])


class ActivityEventValidationTests(unittest.TestCase):
    def test_requires_timezone_aware_recorded_at(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            _event(recorded_at=datetime(2026, 7, 19, 10))

    def test_rejects_unknown_operation_and_status(self) -> None:
        with self.assertRaises(ValueError):
            _event(operation="unknown")
        with self.assertRaises(ValueError):
            _event(status="unknown")


if __name__ == "__main__":
    unittest.main()
