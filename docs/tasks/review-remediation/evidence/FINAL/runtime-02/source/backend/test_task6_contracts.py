from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from accounts.storage import JsonSubscriptionRepository
from core.plans import PlanLimits
from core.usage_costs import ModelRate
from repositories.usage_repository import JsonUsageRepository
from schemas import ChatResponse
from services.entitlements import EntitlementError
from services.synchronous_execution import SynchronousExecution
from services.usage_meter import UsageMeter

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
USER_ID = "0190f4c0-0000-7000-8000-000000000001"
RATE = ModelRate("test-model", 10, 20, "rates-v1")
PLAN = PlanLimits("basic", 1, 2, 50, 12_000, 1_000, 200_000)


class UsageObservabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.usage = JsonUsageRepository(root / "usage.json")
        self.subscriptions = JsonSubscriptionRepository(root / "subscriptions.json")
        self.meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: PLAN,
            reservation_ttl_seconds=60,
            reservation_enabled=True,
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _events(self, output: list[str]) -> list[dict[str, object]]:
        return [json.loads(line.split(":", 2)[-1].strip()) for line in output]

    def test_usage_lifecycle_emits_structured_safe_events(self) -> None:
        with self.assertLogs("untangle.usage", level="INFO") as captured:
            self.meter.reserve("article-op", "payload-hash", "article", 100)
            self.meter.finalize(
                "article-op",
                {"input_tokens": 20, "output_tokens": 5, "actual_cost_micro_usd": 80},
                result_ref="private-result-reference",
            )
            self.meter.reserve("chat-op", "chat-hash", "chat", 40)
            self.meter.release("chat-op", "provider_failed")
            with self.assertRaises(EntitlementError):
                self.meter.reserve("blocked-op", "blocked-hash", "article", 1)

        events = self._events(captured.output)
        self.assertEqual(
            [event["event"] for event in events],
            [
                "usage_reserved",
                "usage_finalized",
                "usage_reserved",
                "usage_released",
                "usage_reserve_blocked",
            ],
        )
        finalized = events[1]
        self.assertEqual(finalized["estimated_cost_micro_usd"], 100)
        self.assertEqual(finalized["actual_cost_micro_usd"], 80)
        serialized = json.dumps(events)
        for forbidden in (
            "payload-hash",
            "chat-hash",
            "private-result-reference",
            "source_text",
            "auth_token",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_expired_reservations_emit_reclaimed_metric(self) -> None:
        self.meter.reserve("expired", "old", "chat", 1, now=NOW - timedelta(minutes=2))
        with self.assertLogs("untangle.usage", level="INFO") as captured:
            self.meter.reserve("replacement", "new", "chat", 1, now=NOW)

        events = self._events(captured.output)
        self.assertEqual(events[0]["event"], "usage_reclaimed")
        self.assertEqual(events[0]["count"], 1)

    def test_immediate_expired_execution_claim_emits_recovery_event(self) -> None:
        moment = datetime.now(UTC)
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=moment,
            plan_loader=lambda _: PLAN,
            reservation_enabled=True,
        )
        operation = meter.reserve("lease-op", "safe-hash", "chat", 1)
        self.assertTrue(
            meter.claim_execution(
                operation.operation_id,
                "expired-owner",
                moment - timedelta(seconds=2),
                moment - timedelta(seconds=1),
            )
        )

        with self.assertLogs("untangle.backend", level="INFO") as captured:
            with SynchronousExecution(
                meter,
                operation,
                kind="chat",
                response_model=ChatResponse,
            ) as execution:
                self.assertIsNone(execution.replay)
                self.assertFalse(
                    meter.claim_execution(
                        operation.operation_id,
                        "competing-owner",
                        moment,
                        moment + timedelta(seconds=30),
                    )
                )
        events = self._events(captured.output)
        self.assertEqual(events[0]["event"], "execution_lease_recovered")
        self.assertEqual(events[0]["kind"], "chat")

    def test_unexpected_finalize_failure_emits_safe_structured_event(self) -> None:
        self.meter.reserve("finalize-error", "secret-payload-hash", "chat", 25)
        with (
            mock.patch.object(
                self.usage, "finalize", side_effect=RuntimeError("storage unavailable")
            ),
            self.assertLogs("untangle.usage", level="ERROR") as captured,
            self.assertRaisesRegex(RuntimeError, "storage unavailable"),
        ):
            self.meter.finalize(
                "finalize-error",
                {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "private_source_text": "do-not-log-source",
                },
                result_ref="do-not-log-private-result",
            )

        events = self._events(captured.output)
        self.assertEqual(events[0]["event"], "usage_finalization_error")
        serialized = json.dumps(events)
        for forbidden in (
            "secret-payload-hash",
            "do-not-log-source",
            "do-not-log-private-result",
        ):
            self.assertNotIn(forbidden, serialized)


class Task6ConfigurationContractTests(unittest.TestCase):
    def test_rollout_defaults_off_and_all_runtime_settings_are_documented(self) -> None:
        env_text = (ROOT / "backend/.env.example").read_text()
        self.assertIn("USAGE_RESERVATION_ENABLED=false", env_text)
        for name in (
            "USAGE_RESERVATION_TTL_SECONDS",
            "SYNC_RESULT_TTL_SECONDS",
            "SYNC_RESULT_MAX_BYTES",
            "SYNC_RESULT_CLEANUP_BATCH_SIZE",
            "SYNC_EXECUTION_LEASE_SECONDS",
            "SYNC_EXECUTION_WAIT_SECONDS",
            "OPENAI_TOKEN_ENCODING",
            "OPENAI_RATE_CARD_VERSION",
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION",
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION",
        ):
            self.assertIn(name, env_text)

    def test_split_agent_turn_range_matches_runtime_maximum(self) -> None:
        env_text = (ROOT / "backend/.env.example").read_text()
        billing = (ROOT / "docs/BILLING.md").read_text()
        for text in (env_text, billing):
            self.assertIn("1..8", text)
        self.assertIn("MAX_SENTENCE_SPLIT_AGENT_TURNS=2", env_text)
        self.assertNotIn("Valid range: 1..32", env_text)
        self.assertNotIn("valid range `1..32`", billing)

    def test_terraform_enables_native_ttl_and_passes_typed_usage_settings(self) -> None:
        data = (ROOT / "infra/modules/reading-assistant-data/main.tf").read_text()
        api = (ROOT / "infra/modules/reading-assistant-api/main.tf").read_text()
        api_vars = (ROOT / "infra/modules/reading-assistant-api/variables.tf").read_text()
        self.assertIn('attribute_name = "expires_at_epoch"', data)
        self.assertIn("enabled        = true", data)
        for name in (
            "USAGE_RESERVATION_ENABLED",
            "USAGE_RESERVATION_TTL_SECONDS",
            "SYNC_RESULT_TTL_SECONDS",
            "SYNC_RESULT_MAX_BYTES",
            "SYNC_RESULT_CLEANUP_BATCH_SIZE",
            "SYNC_EXECUTION_LEASE_SECONDS",
            "SYNC_EXECUTION_WAIT_SECONDS",
            "OPENAI_MAX_INPUT_TOKENS_PER_CALL",
            "MAX_SENTENCE_SPLIT_AGENT_TURNS",
        ):
            self.assertIn(name, api)
        for declaration in (
            'variable "openai_max_input_tokens_per_call"',
            'variable "max_sentence_split_agent_turns"',
        ):
            self.assertIn(declaration, api_vars)
        self.assertIn("default     = false", api_vars)

    def test_terraform_requires_pricing_only_when_enforcement_is_enabled(self) -> None:
        api = (ROOT / "infra/modules/reading-assistant-api/main.tf").read_text()
        self.assertIn('check "usage_pricing_required_when_enforced"', api)
        self.assertIn("!var.usage_reservation_enabled", api)
        for key in (
            "OPENAI_RATE_CARD_VERSION",
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION",
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION",
        ):
            self.assertIn(key, api)
        self.assertIn("tonumber", api)

    def test_api_and_worker_iam_allow_usage_transactions(self) -> None:
        api = (ROOT / "infra/modules/reading-assistant-api/main.tf").read_text()
        self.assertEqual(
            api.count('"dynamodb:TransactWriteItems"'),
            2,
            "both API and worker DynamoDB statements require transactions",
        )

    def test_article_cap_contract_is_order_preserving_prefix(self) -> None:
        design = (
            (ROOT / "docs/superpowers/specs/2026-07-17-plan-usage-metering-design.md")
            .read_text()
            .lower()
        )
        self.assertIn("order-preserving prefix", design)
        self.assertNotIn("skipped or safely truncated", design)

    def test_terraform_roots_wire_usage_settings_and_protect_reserved_keys(self) -> None:
        api = (ROOT / "infra/modules/reading-assistant-api/main.tf").read_text()
        api_vars = (ROOT / "infra/modules/reading-assistant-api/variables.tf").read_text()
        names = (
            "usage_reservation_enabled",
            "usage_reservation_ttl_seconds",
            "sync_result_ttl_seconds",
            "sync_result_max_bytes",
            "sync_result_cleanup_batch_size",
            "sync_execution_lease_seconds",
            "sync_execution_wait_seconds",
            "preload_worker_lease_seconds",
            "openai_max_input_tokens_per_call",
            "max_sentence_split_agent_turns",
            "usage_pricing_and_plan_environment",
        )
        for environment in ("dev", "prod"):
            root_main = (ROOT / f"infra/envs/{environment}/main.tf").read_text()
            root_vars = (ROOT / f"infra/envs/{environment}/variables.tf").read_text()
            for name in names:
                self.assertIn(f'variable "{name}"', root_vars)
                self.assertRegex(
                    root_main,
                    rf"(?m)^\s*{name}\s*=\s*var\.{name}\s*$",
                )

        self.assertLess(
            api.index("var.extra_environment"),
            api.index("local.usage_environment"),
            "reserved usage settings must override extra_environment",
        )
        self.assertIn("RESERVED_USAGE_ENVIRONMENT_KEYS", api_vars)
        self.assertIn("setintersection", api_vars)

    def test_docs_cover_metering_and_operational_contract(self) -> None:
        combined = "\n".join(
            (ROOT / path).read_text()
            for path in (
                "docs/BILLING.md",
                "docs/MONETIZATION.md",
                "docs/adr/0001-composite-usage-metering.md",
            )
        ).lower()
        for phrase in (
            "utc calendar month",
            "pinned snapshot",
            "downgrade",
            "idempotency",
            "hidden cost",
            "shadow",
            "lease recovery",
            "operational recovery",
            "openai_max_input_tokens_per_call=128000",
            "max_sentence_split_agent_turns=2",
            "preload_worker_lease_seconds=900",
            "usage_shadow_observed",
            "tokenizer encoding",
        ):
            self.assertIn(phrase, combined)

    def test_docs_distinguish_active_cost_ceiling_from_migration_tokens(self) -> None:
        combined = "\n".join(
            (ROOT / path).read_text()
            for path in (
                "docs/BILLING.md",
                "docs/MONETIZATION.md",
            )
        ).lower()
        self.assertIn(
            "raw token totals are retained only for migration, calibration, and rollback",
            combined,
        )
        self.assertIn(
            "active hidden monthly hard cost ceiling is integer micro-usd",
            combined,
        )
        for legacy in (
            "tokens / month (hidden safety valve)",
            "monthly token budget as a double-check",
            "hidden monthly token budgets (429 hard ceiling)",
            "the hidden token budget (3m) is what actually protects margin",
        ):
            self.assertNotIn(legacy, combined)


if __name__ == "__main__":
    unittest.main()
