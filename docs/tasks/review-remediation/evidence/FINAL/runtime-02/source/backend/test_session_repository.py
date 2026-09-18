from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from accounts.storage import JsonEmailAuthService
from repositories.json_admin_account_control import JsonAdminAccountControlRepository
from repositories.json_session_repository import JsonSessionRepository
from repositories.memory_session_repository import MemorySessionRepository
from services.admin_accounts import AdminAccounts


class PausingJsonEmailAuthService(JsonEmailAuthService):
    def __init__(
        self,
        *args,
        sessions_read: threading.Event,
        continue_sessions_read: threading.Event,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._sessions_read = sessions_read
        self._continue_sessions_read = continue_sessions_read

    def _read_sessions_unlocked(self):
        sessions = super()._read_sessions_unlocked()
        self._sessions_read.set()
        if not self._continue_sessions_read.wait(timeout=2):
            raise TimeoutError("Test did not release the session reader")
        return sessions


class RecordingJsonSessionRepository(JsonSessionRepository):
    def __init__(self, *args, revocation_started: threading.Event, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._revocation_started = revocation_started

    def revoke_all(self, user_id: str) -> int:
        self._revocation_started.set()
        return super().revoke_all(user_id)


class SessionRepositoryContract:
    def create_repository(self):
        raise NotImplementedError

    def test_revoke_all_returns_count_and_preserves_other_sessions(self) -> None:
        repository = self.create_repository()

        self.assertEqual(repository.revoke_all("user-1"), 2)
        self.assertEqual(repository.revoke_all("user-1"), 0)
        self.assertEqual(repository.sessions, [{"token": "c", "user_id": "user-2"}])


class MemorySessionRepositoryTests(SessionRepositoryContract, unittest.TestCase):
    def create_repository(self):
        return MemorySessionRepository(
            [
                {"token": "a", "user_id": "user-1"},
                {"token": "b", "user_id": "user-1"},
                {"token": "c", "user_id": "user-2"},
            ]
        )


class JsonSessionRepositoryTests(SessionRepositoryContract, unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tempdir.name) / "auth_sessions.json"
        self.users_path = Path(self._tempdir.name) / "users.json"

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def create_repository(self):
        sessions = [
            {"token": "a", "user_id": "user-1"},
            {"token": "b", "user_id": "user-1"},
            {"token": "c", "user_id": "user-2"},
        ]
        self.path.write_text(json.dumps(sessions), encoding="utf-8")
        return JsonSessionRepository(self.path)

    def test_corrupt_file_fails_closed(self) -> None:
        self.path.write_text('{"not":"a-list"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            JsonSessionRepository(self.path).revoke_all("user-1")
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"not":"a-list"}')

    def test_auth_does_not_replace_a_corrupt_session_document(self) -> None:
        for original in ('{"not":"a-list"}', '[{"token":"missing-session-fields"}]'):
            with self.subTest(document=original):
                self.path.write_text(original, encoding="utf-8")
                auth = JsonEmailAuthService(self.users_path, self.path)

                with self.assertRaises(ValueError):
                    auth.login(email="reader@example.test")

                self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_login_and_logout_share_one_canonical_session_lock_across_a_symlink(self) -> None:
        seed_auth = JsonEmailAuthService(self.users_path, self.path)
        old_token, user = seed_auth.login(email="reader@example.test")
        alias = Path(self._tempdir.name) / "auth_sessions_alias.json"
        alias.symlink_to(self.path)
        sessions_read = threading.Event()
        continue_sessions_read = threading.Event()
        login_auth = PausingJsonEmailAuthService(
            self.users_path,
            alias,
            sessions_read=sessions_read,
            continue_sessions_read=continue_sessions_read,
        )
        logout_auth = JsonEmailAuthService(self.users_path, self.path)
        login_result: list[tuple[str, object]] = []
        logout_finished = threading.Event()

        login_thread = threading.Thread(
            target=lambda: login_result.append(login_auth.login(email="reader@example.test")),
        )
        logout_thread = threading.Thread(
            target=lambda: (logout_auth.logout(old_token), logout_finished.set()),
        )
        login_thread.start()
        self.assertTrue(sessions_read.wait(timeout=2))
        logout_thread.start()
        self.assertFalse(logout_finished.wait(timeout=0.1))
        continue_sessions_read.set()
        login_thread.join(timeout=2)
        logout_thread.join(timeout=2)

        self.assertFalse(login_thread.is_alive())
        self.assertFalse(logout_thread.is_alive())
        self.assertEqual(login_auth._sessions_path, self.path.resolve())
        self.assertIsNone(seed_auth.resolve_user(old_token))
        new_token, new_user = login_result[0]
        self.assertEqual(new_user.id, user.id)
        self.assertEqual(logout_auth.resolve_user(new_token).id, user.id)

    def test_expiry_cleanup_cannot_restore_sessions_after_admin_revocation_and_reactivation(
        self,
    ) -> None:
        now = datetime.now(UTC)
        self.path.write_text(
            json.dumps(
                [
                    {
                        "token": "expired-target",
                        "user_id": "target-1",
                        "expires_at": (now - timedelta(minutes=1)).isoformat(),
                    },
                    {
                        "token": "active-target",
                        "user_id": "target-1",
                        "expires_at": (now + timedelta(minutes=1)).isoformat(),
                    },
                    {
                        "token": "active-other",
                        "user_id": "other-1",
                        "expires_at": (now + timedelta(minutes=1)).isoformat(),
                    },
                ]
            ),
            encoding="utf-8",
        )
        sessions_read = threading.Event()
        continue_sessions_read = threading.Event()
        revocation_started = threading.Event()
        alias = Path(self._tempdir.name) / "auth_sessions_admin_alias.json"
        alias.symlink_to(self.path)
        cleanup_auth = PausingJsonEmailAuthService(
            self.users_path,
            self.path,
            sessions_read=sessions_read,
            continue_sessions_read=continue_sessions_read,
        )
        sessions = RecordingJsonSessionRepository(
            alias,
            revocation_started=revocation_started,
        )
        controls = JsonAdminAccountControlRepository(
            Path(self._tempdir.name) / "account_controls.json"
        )
        admin = AdminAccounts(
            controls,
            sessions,
            user_exists=lambda user_id: user_id == "target-1",
        )
        admin_finished = threading.Event()

        cleanup_thread = threading.Thread(
            target=lambda: cleanup_auth.resolve_user("expired-target")
        )

        def suspend_and_reactivate() -> None:
            admin.suspend(
                target_user_id="target-1",
                actor_user_id="admin-1",
                actor_email="admin@example.test",
                reason="Policy violation",
                correlation_id="session-race-1",
                occurred_at=now,
            )
            admin.reactivate(
                target_user_id="target-1",
                actor_user_id="admin-1",
                actor_email="admin@example.test",
                reason="Appeal approved",
                correlation_id="session-race-2",
                occurred_at=now + timedelta(minutes=1),
            )
            admin_finished.set()

        admin_thread = threading.Thread(target=suspend_and_reactivate)
        cleanup_thread.start()
        self.assertTrue(sessions_read.wait(timeout=2))
        admin_thread.start()
        self.assertTrue(revocation_started.wait(timeout=2))
        self.assertFalse(admin_finished.wait(timeout=0.1))
        continue_sessions_read.set()
        cleanup_thread.join(timeout=2)
        admin_thread.join(timeout=2)

        self.assertFalse(cleanup_thread.is_alive())
        self.assertFalse(admin_thread.is_alive())
        self.assertTrue(admin_finished.is_set())
        self.assertEqual(sessions._path, self.path.resolve())
        self.assertEqual(controls.get_control("target-1").status, "active")
        self.assertEqual(
            sessions.sessions,
            [
                {
                    "token": "active-other",
                    "user_id": "other-1",
                    "expires_at": (now + timedelta(minutes=1)).isoformat(),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
