from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone

from deps import (
    get_admin_account_control_repository,
    get_admin_accounts,
    get_session_repository,
)
from repositories.json_admin_account_control import JsonAdminAccountControlRepository
from repositories.json_session_repository import JsonSessionRepository
from repositories.memory_admin_account_control import MemoryAdminAccountControlRepository
from repositories.memory_session_repository import MemorySessionRepository
from services.admin_accounts import (
    AdminAccounts,
    SessionRevocationError,
    TargetUserNotFoundError,
)

NOW = datetime(2026, 7, 20, 10, tzinfo=UTC)


class FailingOnceSessions(MemorySessionRepository):
    def __init__(self) -> None:
        super().__init__([{"token": "secret-token", "user_id": "target-1"}])
        self.attempts = 0

    def revoke_all(self, user_id: str) -> int:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("database password and secret-token")
        return super().revoke_all(user_id)


class AdminAccountsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controls = MemoryAdminAccountControlRepository()
        self.sessions = MemorySessionRepository(
            [
                {"token": "a", "user_id": "target-1"},
                {"token": "b", "user_id": "other"},
            ]
        )
        self.existing_ids = {"target-1"}
        self.service = AdminAccounts(
            self.controls,
            self.sessions,
            user_exists=lambda user_id: user_id in self.existing_ids,
        )

    def suspend(self, **overrides):
        values = {
            "target_user_id": "target-1",
            "actor_user_id": "admin-1",
            "actor_email": "ADMIN@example.com",
            "reason": "  Policy violation  ",
            "correlation_id": "request-1",
            "occurred_at": NOW,
        }
        values.update(overrides)
        return self.service.suspend(**values)

    def test_suspension_validates_normalizes_audits_and_revokes_sessions(self) -> None:
        result = self.suspend(
            occurred_at=datetime(2026, 7, 20, 19, tzinfo=timezone(timedelta(hours=9)))
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.control.suspension_reason, "Policy violation")
        self.assertEqual(result.control.suspended_at, NOW)
        self.assertEqual(result.audit_event.actor_email, "admin@example.com")
        parsed = uuid.UUID(result.audit_event.id)
        self.assertEqual(parsed.version, 7)
        self.assertEqual(parsed.variant, uuid.RFC_4122)
        self.assertEqual(self.sessions.sessions, [{"token": "b", "user_id": "other"}])

    def test_nonexistent_target_is_rejected_without_creating_control(self) -> None:
        with self.assertRaises(TargetUserNotFoundError):
            self.suspend(target_user_id="missing")

        self.assertEqual(self.controls.query_audits(limit=10).events, ())
        self.assertEqual(self.controls.get_control("missing").status, "active")

    def test_reason_validation(self) -> None:
        for reason in ("", " ", "x" * 501):
            with self.subTest(reason_length=len(reason)), self.assertRaises(ValueError):
                self.suspend(reason=reason)

    def test_reactivation_does_not_revoke_sessions(self) -> None:
        self.suspend()
        self.sessions.sessions.append({"token": "new", "user_id": "target-1"})

        result = self.service.reactivate(
            target_user_id="target-1",
            actor_user_id="admin-1",
            actor_email="admin@example.com",
            reason="Appeal approved",
            correlation_id="request-2",
            occurred_at=NOW + timedelta(minutes=1),
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.control.status, "active")
        self.assertIn({"token": "new", "user_id": "target-1"}, self.sessions.sessions)

    def test_failed_revocation_keeps_commit_and_retry_recovers(self) -> None:
        sessions = FailingOnceSessions()
        service = AdminAccounts(
            self.controls,
            sessions,
            user_exists=lambda user_id: user_id == "target-1",
        )
        arguments = {
            "target_user_id": "target-1",
            "actor_user_id": "admin-1",
            "actor_email": "admin@example.com",
            "reason": "Policy violation",
            "correlation_id": "request-safe-123",
            "occurred_at": NOW,
        }

        with self.assertLogs("services.admin_accounts", "ERROR") as logs:
            with self.assertRaises(SessionRevocationError):
                service.suspend(**arguments)

        self.assertEqual(self.controls.get_control("target-1").status, "suspended")
        self.assertEqual(len(self.controls.query_audits(limit=10).events), 1)
        message = "\n".join(logs.output)
        self.assertIn("request-safe-123", message)
        self.assertNotIn("password", message)
        self.assertNotIn("secret-token", message)

        retry = service.suspend(**arguments)
        self.assertFalse(retry.changed)
        self.assertEqual(sessions.attempts, 2)
        self.assertEqual(sessions.sessions, [])
        self.assertEqual(len(self.controls.query_audits(limit=10).events), 1)


class AdminAccountsDependencyTests(unittest.TestCase):
    def test_json_dependencies_are_singletons(self) -> None:
        controls = get_admin_account_control_repository()
        sessions = get_session_repository()
        service = get_admin_accounts()

        self.assertIsInstance(controls, JsonAdminAccountControlRepository)
        self.assertIs(controls, get_admin_account_control_repository())
        self.assertIsInstance(sessions, JsonSessionRepository)
        self.assertIs(sessions, get_session_repository())
        self.assertIsInstance(service, AdminAccounts)
        self.assertIs(service, get_admin_accounts())


if __name__ == "__main__":
    unittest.main()
