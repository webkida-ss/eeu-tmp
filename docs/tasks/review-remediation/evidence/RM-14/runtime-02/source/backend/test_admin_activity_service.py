from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone

from deps import get_admin_activity_repository
from repositories.json_admin_activity import JsonAdminActivityRepository
from repositories.memory_admin_activity import MemoryAdminActivityRepository
from services.admin_activity import AdminActivityService


class AdminActivityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = MemoryAdminActivityRepository()
        self.service = AdminActivityService(self.repository)

    def test_records_explicit_activity_fields_with_uuid7(self) -> None:
        recorded_at = datetime(2026, 7, 19, 19, tzinfo=timezone(timedelta(hours=9)))

        event = self.service.record_activity(
            source_id="request-1",
            user_id="user-1",
            operation="chat",
            status="success",
            recorded_at=recorded_at,
            input_tokens=10,
            output_tokens=4,
            tokens=14,
            actual_cost_micro_usd=18,
            model="model-1",
        )

        parsed_id = uuid.UUID(event.id)
        self.assertEqual(parsed_id.version, 7)
        self.assertEqual(parsed_id.variant, uuid.RFC_4122)
        self.assertEqual(
            event.recorded_at,
            datetime(2026, 7, 19, 10, tzinfo=UTC),
        )
        self.assertEqual(event.tokens, 14)

    def test_defaults_recorded_at_to_aware_utc(self) -> None:
        event = self.service.record_activity(
            source_id="request-1",
            user_id="user-1",
            operation="article",
            status="quota_blocked",
        )

        self.assertIsNotNone(event.recorded_at.tzinfo)
        self.assertEqual(event.recorded_at.utcoffset(), timedelta(0))

    def test_recording_same_account_source_returns_original_event(self) -> None:
        first = self.service.record_activity(
            source_id="request-1",
            user_id="user-1",
            operation="article",
            status="success",
        )
        second = self.service.record_activity(
            source_id="request-1",
            user_id="user-1",
            operation="chat",
            status="failed",
        )

        self.assertEqual(second, first)
        other_account = self.service.record_activity(
            source_id="request-1",
            user_id="user-2",
            operation="article",
            status="success",
        )
        self.assertNotEqual(other_account.id, first.id)
        self.assertEqual(other_account.user_id, "user-2")
        self.assertEqual(other_account.source_id, first.source_id)

    def test_rejects_naive_datetime(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.service.record_activity(
                source_id="request-1",
                user_id="user-1",
                operation="article",
                status="success",
                recorded_at=datetime(2026, 7, 19, 10),
            )

    def test_rejects_negative_or_boolean_numeric_fields(self) -> None:
        for field, value in (
            ("input_tokens", -1),
            ("output_tokens", -1),
            ("tokens", -1),
            ("actual_cost_micro_usd", -1),
            ("tokens", True),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.service.record_activity(
                    source_id=f"request-{field}-{value}",
                    user_id="user-1",
                    operation="article",
                    status="success",
                    **{field: value},
                )

    def test_sanitizes_and_limits_error_code_and_model(self) -> None:
        event = self.service.record_activity(
            source_id="request-1",
            user_id="user-1",
            operation="article",
            status="failed",
            error_code="  private payload!\n" + "x" * 100,
            model="  vendor/model<script>  " + "y" * 200,
        )

        self.assertEqual(event.error_code, "private_payload_" + "x" * 48)
        self.assertEqual(len(event.error_code or ""), 64)
        self.assertNotIn("\n", event.error_code or "")
        self.assertEqual(event.model, "vendor/model_script_" + "y" * 108)
        self.assertEqual(len(event.model or ""), 128)

    def test_empty_sanitized_metadata_becomes_none(self) -> None:
        event = self.service.record_activity(
            source_id="request-1",
            user_id="user-1",
            operation="article",
            status="failed",
            error_code=" \n ",
            model=" \t ",
        )

        self.assertIsNone(event.error_code)
        self.assertIsNone(event.model)


class AdminActivityDependencyTests(unittest.TestCase):
    def test_dependency_returns_one_json_repository(self) -> None:
        first = get_admin_activity_repository()
        second = get_admin_activity_repository()

        self.assertIsInstance(first, JsonAdminActivityRepository)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
