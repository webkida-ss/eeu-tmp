from __future__ import annotations

import json
import tempfile
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from repositories.admin_account_control import AccountControl
from repositories.json_admin_account_control import JsonAdminAccountControlRepository
from repositories.memory_admin_account_control import MemoryAdminAccountControlRepository
from schemas import generate_uuid7

NOW = datetime(2026, 7, 20, 1, tzinfo=UTC)


class AdminAccountControlContract:
    def create_repository(self):
        raise NotImplementedError

    def transition(self, repository, **overrides):
        values = {
            "target_user_id": "target-1",
            "desired_status": "suspended",
            "actor_user_id": "admin-1",
            "actor_email": "admin@example.com",
            "reason": "Policy violation",
            "correlation_id": "request-1",
            "occurred_at": NOW,
            "audit_id": generate_uuid7(),
        }
        values.update(overrides)
        return repository.transition(**values)

    def test_missing_control_is_active(self) -> None:
        self.assertEqual(
            self.create_repository().get_control("missing"),
            AccountControl(user_id="missing", status="active"),
        )

    def test_transition_atomically_changes_control_and_appends_audit(self) -> None:
        repository = self.create_repository()
        result = self.transition(repository)

        self.assertTrue(result.changed)
        self.assertEqual(result.control.status, "suspended")
        self.assertEqual(result.control.suspended_at, NOW)
        self.assertEqual(result.control.suspension_reason, "Policy violation")
        self.assertIsNotNone(result.audit_event)
        page = repository.query_audits(target_user_id="target-1", limit=10)
        self.assertEqual(page.events, (result.audit_event,))

    def test_identical_retry_does_not_append_audit(self) -> None:
        repository = self.create_repository()
        first = self.transition(repository)
        second = self.transition(repository, audit_id=generate_uuid7())

        self.assertFalse(second.changed)
        self.assertEqual(second.control, first.control)
        self.assertIsNone(second.audit_event)
        self.assertEqual(len(repository.query_audits(limit=10).events), 1)

    def test_reactivation_clears_suspension_fields(self) -> None:
        repository = self.create_repository()
        self.transition(repository)
        result = self.transition(
            repository,
            desired_status="active",
            reason="Appeal approved",
            occurred_at=NOW + timedelta(minutes=1),
            audit_id=generate_uuid7(),
        )

        self.assertTrue(result.changed)
        self.assertEqual(
            result.control,
            AccountControl(user_id="target-1", status="active"),
        )
        self.assertEqual(result.audit_event.previous_status, "suspended")
        self.assertEqual(result.audit_event.new_status, "active")

    def test_audit_query_is_filterable_deterministic_and_paged(self) -> None:
        repository = self.create_repository()
        first = self.transition(repository)
        second = self.transition(
            repository,
            desired_status="active",
            actor_user_id="admin-2",
            actor_email="other@example.com",
            reason="Restored",
            occurred_at=NOW + timedelta(minutes=1),
            audit_id=generate_uuid7(),
        )
        page = repository.query_audits(target_user_id="target-1", limit=1)
        self.assertEqual(page.events, (first.audit_event,))
        self.assertIsNotNone(page.next_cursor)
        last = repository.query_audits(target_user_id="target-1", limit=1, cursor=page.next_cursor)
        self.assertEqual(last.events, (second.audit_event,))
        self.assertIsNone(last.next_cursor)
        self.assertEqual(
            repository.query_audits(actor_user_id="admin-2", limit=10).events,
            (second.audit_event,),
        )

    def test_rejects_invalid_reason_datetime_and_audit_uuid(self) -> None:
        repository = self.create_repository()
        for reason in ("", "   ", "x" * 501):
            with self.subTest(reason_length=len(reason)), self.assertRaises(ValueError):
                self.transition(repository, reason=reason)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.transition(repository, occurred_at=datetime(2026, 7, 20))
        with self.assertRaisesRegex(ValueError, "UUID v7"):
            self.transition(repository, audit_id=str(uuid.uuid4()))

    def test_idempotent_retry_still_validates_required_actor_metadata(self) -> None:
        repository = self.create_repository()
        self.transition(repository)

        with self.assertRaisesRegex(ValueError, "actor_user_id"):
            self.transition(repository, actor_user_id="", audit_id=generate_uuid7())


class MemoryAdminAccountControlTests(AdminAccountControlContract, unittest.TestCase):
    def create_repository(self):
        return MemoryAdminAccountControlRepository()


class JsonAdminAccountControlTests(AdminAccountControlContract, unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tempdir.name) / "admin_control.json"

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def create_repository(self):
        return JsonAdminAccountControlRepository(self.path)

    def test_document_is_versioned_and_uses_utc(self) -> None:
        offset = timezone(timedelta(hours=9))
        self.transition(
            self.create_repository(),
            occurred_at=datetime(2026, 7, 20, 10, tzinfo=offset),
        )
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], 1)
        self.assertEqual(set(document), {"version", "account_controls", "admin_audit_events"})
        control = document["account_controls"]["target-1"]
        self.assertEqual(control["suspended_at"], "2026-07-20T01:00:00+00:00")
        self.assertEqual(
            document["admin_audit_events"][0]["occurred_at"],
            "2026-07-20T01:00:00+00:00",
        )

    def test_corrupt_document_fails_closed_without_overwrite(self) -> None:
        original = '{"version":1,"account_controls":[]}'
        self.path.write_text(original, encoding="utf-8")

        with self.assertRaises(ValueError):
            self.transition(self.create_repository())

        self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_concurrent_same_transition_creates_one_audit(self) -> None:
        barrier = threading.Barrier(2)
        results = []

        def suspend() -> None:
            repository = self.create_repository()
            barrier.wait()
            results.append(self.transition(repository, audit_id=generate_uuid7()))

        threads = [threading.Thread(target=suspend) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(result.changed for result in results), 1)
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(document["admin_audit_events"]), 1)


if __name__ == "__main__":
    unittest.main()
