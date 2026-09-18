from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from accounts.storage import JsonSubscriptionRepository
from core.plans import PlanLimits
from core.usage_costs import ModelRate
from repositories.usage_repository import (
    JsonUsageRepository,
    UsageOperationNotFound,
    UsageOperationStateError,
)
from services.entitlements import EntitlementError, build_guard, usage_summary
from services.usage_meter import UsageMeter

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
USER_ID = "0190f4c0-0000-7000-8000-000000000001"
RATE = ModelRate(
    model="test-model",
    input_micro_usd_per_million=10,
    output_micro_usd_per_million=20,
    version="rates-v1",
)
BASIC = PlanLimits("basic", 5, 10, 50, 12_000, 1_000, 200_000)
PRO = PlanLimits("pro", 20, 40, 200, 48_000, 10_000, 3_000_000)


class UsageMeterTests(unittest.TestCase):
    def test_reclaim_failure_is_logged_without_blocking_new_reservation(self) -> None:
        meter = self.meter()
        with (
            patch.object(
                self.usage,
                "reclaim_expired",
                side_effect=RuntimeError("malformed legacy operation"),
            ),
            self.assertLogs("untangle.usage", level="ERROR") as captured,
        ):
            operation = meter.reserve("reclaim-isolated", "payload", "cost", 1)

        self.assertEqual(operation.state, "reserved")
        self.assertTrue(any("usage_reclaim_error" in line for line in captured.output))

    def test_finalize_emits_overage_telemetry_without_rejecting(self) -> None:
        meter = self.meter(plan=PlanLimits("basic", 5, 10, 50, 12_000, 100, 200_000))
        meter.reserve("overage", "payload", "cost", 80)
        with self.assertLogs("untangle.usage", level="INFO") as captured:
            finalized = meter.finalize("overage", {"actual_cost_micro_usd": 150})

        self.assertEqual(finalized.actual_cost_micro_usd, 150)
        self.assertTrue(any("usage_overage_observed" in line for line in captured.output))

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.usage = JsonUsageRepository(root / "usage.json")
        self.subscriptions = JsonSubscriptionRepository(root / "subscriptions.json")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def meter(self, *, plan: PlanLimits = BASIC) -> UsageMeter:
        return UsageMeter(
            subscription_repository=self.subscriptions,
            usage_repository=self.usage,
            user_id=USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _plan_id: plan,
            reservation_ttl_seconds=60,
            reservation_enabled=True,
        )

    def test_reserves_article_chat_and_cost_only(self) -> None:
        meter = self.meter()
        article = meter.reserve("article-op", "article-hash", "article", 100)
        chat = meter.reserve("chat-op", "chat-hash", "chat", 40)
        cost = meter.reserve("cost-op", "cost-hash", "cost", 20)

        self.assertEqual((article.articles, article.chats, article.cost_micro_usd), (1, 0, 100))
        self.assertEqual((chat.articles, chat.chats, chat.cost_micro_usd), (0, 1, 40))
        self.assertEqual((cost.articles, cost.chats, cost.cost_micro_usd), (0, 0, 20))
        self.assertEqual(article.month, "2026-07")
        self.assertEqual(article.plan_id, "basic")
        self.assertEqual(article.rate_card_version, "rates-v1")
        self.assertEqual(article.article_limit, BASIC.articles_per_month)
        self.assertEqual(article.chat_limit, BASIC.chats_per_month)
        self.assertEqual(article.cost_micro_usd_limit, BASIC.cost_micro_usd_per_month)
        self.assertEqual(article.sentences_per_article, BASIC.sentences_per_article)
        self.assertEqual(article.source_tokens_per_article, BASIC.source_tokens_per_article)
        self.assertEqual(article.model, "test-model")
        self.assertEqual(article.input_micro_usd_per_million, 10)
        self.assertEqual(article.output_micro_usd_per_million, 20)
        self.assertEqual(article.expires_at, NOW + timedelta(seconds=60))

    def test_meter_uses_the_explicit_provider_mode_for_mock_entitlements(self) -> None:
        self.subscriptions.upsert(
            USER_ID,
            {
                "plan": "pro",
                "status": "active",
                "entitlement_provider": "mock",
            },
        )
        resolved: list[str] = []

        def load_plan(plan_id: str | None) -> PlanLimits:
            resolved.append(str(plan_id))
            return PRO if plan_id == "pro" else BASIC

        stripe_meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=load_plan,
            provider_mode="stripe",
        )
        self.assertEqual(stripe_meter.current_plan().plan_id, "basic")
        mock_meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=load_plan,
            provider_mode="mock",
        )
        self.assertEqual(mock_meter.current_plan().plan_id, "pro")
        self.assertEqual(resolved, ["basic", "pro"])

    def test_finalize_records_usage_snapshot_and_release_records_reason(self) -> None:
        meter = self.meter()
        meter.reserve("article-op", "article-hash", "article", 100)
        finalized = meter.finalize(
            "article-op",
            usage={
                "input_tokens": 20,
                "output_tokens": 5,
                "total_tokens": 25,
                "actual_cost_micro_usd": 80,
                "model": "resolved-model",
                "rate_card_version": "rates-v1",
            },
            result_ref="article-1",
        )
        meter.reserve("chat-op", "chat-hash", "chat", 20)
        released = meter.release("chat-op", "provider_failed")

        self.assertEqual(finalized.state, "finalized")
        self.assertEqual(finalized.tokens, 25)
        self.assertEqual(finalized.actual_cost_micro_usd, 80)
        self.assertEqual(finalized.result_ref, "article-1")
        self.assertEqual(released.state, "released")
        self.assertEqual(released.release_reason, "provider_failed")

    def test_finalize_accepts_usage_tally_cost_field(self) -> None:
        meter = self.meter()
        meter.reserve("cost-field", "payload", "cost", 100)

        operation = meter.finalize(
            "cost-field",
            usage={
                "input_tokens": 3,
                "output_tokens": 2,
                "total_tokens": 5,
                "cost_micro_usd": 7,
                "model": "test-model",
                "rate_card_version": "rates-v1",
            },
            result_ref=None,
        )

        self.assertEqual(operation.actual_cost_micro_usd, 7)

    def test_lazy_reclaim_makes_expired_capacity_available(self) -> None:
        tiny = PlanLimits("basic", 5, 1, 50, 12_000, 1_000, 200_000)
        meter = self.meter(plan=tiny)
        meter.reserve("expired", "old", "chat", 1, now=NOW - timedelta(minutes=2))

        operation = meter.reserve("replacement", "new", "chat", 1, now=NOW)

        self.assertEqual(operation.state, "reserved")
        self.assertEqual(
            self.usage.get_operation(USER_ID, "expired").release_reason,
            "reservation_expired",
        )

    def test_reserve_normalizes_period_and_expiry_to_utc(self) -> None:
        local_time = datetime(2026, 8, 1, 0, 30, tzinfo=timezone(timedelta(hours=14)))
        operation = self.meter().reserve("utc-boundary", "payload", "cost", 1, now=local_time)

        self.assertEqual(operation.month, "2026-07")
        self.assertEqual(operation.expires_at.utcoffset(), timedelta(0))
        self.assertEqual(
            operation.expires_at,
            datetime(2026, 7, 31, 10, 31, tzinfo=UTC),
        )

    def test_reservation_snapshots_tokenizer_encoding(self) -> None:
        with patch.dict("os.environ", {"OPENAI_TOKEN_ENCODING": "encoding-v1"}):
            operation = self.meter().reserve("tokenizer-snapshot", "payload", "cost", 1)

        self.assertEqual(operation.tokenizer_encoding, "encoding-v1")

    def test_reserve_rejects_naive_datetime(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.meter().reserve("naive", "payload", "cost", 1, now=datetime(2026, 7, 1))

    def test_repository_errors_map_to_stable_entitlement_errors(self) -> None:
        tiny = PlanLimits("basic", 1, 1, 50, 12_000, 10, 200_000)
        meter = self.meter(plan=tiny)
        meter.reserve("article-1", "a", "article", 0)
        with self.assertRaises(EntitlementError) as article:
            meter.reserve("article-2", "b", "article", 0)
        self.assertEqual(
            (article.exception.code, article.exception.status_code), ("article_quota_exceeded", 402)
        )

        meter.reserve("cost-1", "c", "cost", 10)
        with self.assertRaises(EntitlementError) as cost:
            meter.reserve("cost-2", "d", "cost", 1)
        self.assertEqual(
            (cost.exception.code, cost.exception.status_code), ("token_budget_exceeded", 429)
        )

        meter.reserve("chat-1", "chat-a", "chat", 0)
        with self.assertRaises(EntitlementError) as chat:
            meter.reserve("chat-2", "chat-b", "chat", 0)
        self.assertEqual(
            (chat.exception.code, chat.exception.status_code), ("chat_quota_exceeded", 402)
        )

        with self.assertRaises(EntitlementError) as conflict:
            meter.reserve("article-1", "different", "article", 0)
        self.assertEqual(
            (conflict.exception.code, conflict.exception.status_code),
            ("operation_payload_conflict", 409),
        )

    def test_disabled_rollout_is_noop_but_keeps_lifecycle_shape(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
        )
        reserved = meter.reserve("shadow", "payload", "article", 999_999)
        finalized = meter.finalize(
            "shadow",
            usage={"input_tokens": 2, "output_tokens": 3, "actual_cost_micro_usd": 5},
            result_ref="result",
        )

        self.assertEqual(reserved.state, "reserved")
        self.assertEqual(finalized.state, "finalized")
        self.assertEqual(finalized.tokens, 5)
        self.assertEqual(self.usage.get_month(USER_ID, "2026-07")["reserved_articles"], 0)

    def test_durable_shadow_settles_once_without_reserving_paid_capacity(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
            durable_shadow=True,
        )
        operation = meter.reserve("durable-shadow", "payload", "article", 13)
        meter.save_result(
            operation.operation_id,
            {
                "kind": "preload",
                "state": "completed",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "actual_cost_micro_usd": 17,
                    "usage_complete": True,
                },
            },
        )
        pending = meter.prepare_shadow_settlement(
            operation.operation_id, outcome="success", result_ref="preload:durable-shadow"
        )
        settled = meter.settle_shadow(operation.operation_id)

        self.assertEqual(pending.shadow_pending_outcome, "success")
        self.assertEqual(settled.shadow_outcome, "success")
        self.assertEqual((settled.actual_articles, settled.tokens), (1, 5))
        self.assertEqual(self.usage.get_month(USER_ID, "2026-07")["reserved_articles"], 0)
        self.assertEqual(meter.settle_shadow(operation.operation_id), settled)

    def test_durable_shadow_settlement_logs_without_repeating_accounting(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
            durable_shadow=True,
        )
        operation = meter.reserve("durable-shadow-observed", "payload", "article", 13)
        meter.save_result(
            operation.operation_id,
            {
                "kind": "preload",
                "state": "completed",
                "private_source_text": "never-log",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "actual_cost_micro_usd": 17,
                    "usage_complete": True,
                },
            },
        )
        meter.prepare_shadow_settlement(
            operation.operation_id,
            outcome="success",
            result_ref="preload:durable-shadow-observed",
        )

        with self.assertLogs("untangle.usage", level="INFO") as captured:
            settled = meter.settle_shadow(operation.operation_id)
            replay = meter.settle_shadow(operation.operation_id)

        events = [
            __import__("json").loads(line.split(":", 2)[-1].strip())
            for line in captured.output
        ]
        self.assertEqual(
            [event["event"] for event in events],
            ["usage_shadow_observed", "usage_shadow_observed"],
        )
        self.assertEqual(
            events[0],
            {
                "event": "usage_shadow_observed",
                "metric_name": "usage_shadow_observed",
                "metric_value": 1,
                "operation_id": operation.operation_id,
                "meter": "article",
                "outcome": "succeeded",
                "input_tokens": 3,
                "output_tokens": 2,
                "total_tokens": 5,
                "estimated_cost_micro_usd": 13,
                "actual_cost_micro_usd": 17,
                "model": RATE.model,
                "rate_card_version": RATE.version,
                "tokenizer_encoding": operation.tokenizer_encoding,
                "enforcement": "shadow",
                "pricing_available": True,
            },
        )
        self.assertEqual(replay, settled)
        self.assertNotIn("never-log", captured.output[0])
        month = self.usage.get_month(USER_ID, "2026-07")
        self.assertEqual(
            (month["articles"], month["tokens"], month["shadow_cost_micro_usd"]),
            (1, 5, 17),
        )

    def test_disabled_shadow_observation_persists_cost_without_visible_usage(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
        )
        before = self.usage.get_month(USER_ID, "2026-07")
        self.assertTrue(
            hasattr(meter, "observe_shadow"),
            "disabled metering must expose non-enforcing shadow observation",
        )

        with self.assertLogs("untangle.usage", level="INFO") as captured:
            meter.observe_shadow(
                "shadow-observed",
                "chat",
                100,
                {
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "total_tokens": 25,
                    "actual_cost_micro_usd": 80,
                },
                outcome="succeeded",
            )

        event = __import__("json").loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(event["event"], "usage_shadow_observed")
        self.assertEqual(event["estimated_cost_micro_usd"], 100)
        self.assertEqual(event["actual_cost_micro_usd"], 80)
        self.assertEqual(event["input_tokens"], 20)
        self.assertEqual(event["output_tokens"], 5)
        self.assertEqual(event["model"], RATE.model)
        self.assertEqual(event["rate_card_version"], RATE.version)
        self.assertEqual(event["outcome"], "succeeded")
        after = self.usage.get_month(USER_ID, "2026-07")
        self.assertEqual(after["articles"], before["articles"])
        self.assertEqual(after["chats"], before["chats"])
        self.assertEqual(after["tokens"], before["tokens"])
        self.assertEqual(after["shadow_cost_micro_usd"], 80)

    def test_shadow_conservative_failure_uses_estimate_without_private_payload(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
        )
        self.assertTrue(hasattr(meter, "observe_shadow"))
        with self.assertLogs("untangle.usage", level="INFO") as captured:
            meter.observe_shadow(
                "shadow-failure",
                "cost",
                77,
                {"private_source_text": "never-log", "input_tokens": 3},
                outcome="conservative_failure",
            )

        event = __import__("json").loads(captured.output[0].split(":", 2)[-1].strip())
        self.assertEqual(event["actual_cost_micro_usd"], 77)
        self.assertEqual(event["outcome"], "conservative_failure")
        self.assertNotIn("never-log", captured.output[0])

    def test_disabled_rollout_does_not_require_model_pricing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            meter = UsageMeter(
                self.subscriptions,
                self.usage,
                USER_ID,
                now=NOW,
                plan_loader=lambda _: BASIC,
                reservation_enabled=False,
            )

        operation = meter.reserve("shadow-unpriced", "payload", "cost", 10)
        self.assertEqual(operation.rate_card_version, "")
        self.assertEqual(operation.model, "")

    def test_disabled_finalize_replay_returns_first_settlement(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
        )
        meter.reserve("replay", "payload", "article", 10)
        first = meter.finalize(
            "replay",
            usage={"total_tokens": 5, "actual_cost_micro_usd": 3},
            result_ref="first",
        )
        replay = meter.finalize(
            "replay",
            usage={"total_tokens": 999, "actual_cost_micro_usd": 999},
            result_ref="different",
        )

        self.assertEqual(replay, first)

    def test_disabled_lifecycle_uses_stable_not_found_and_state_errors(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=False,
        )
        with self.assertRaises(UsageOperationNotFound):
            meter.finalize("missing", usage={})
        with self.assertRaises(UsageOperationNotFound):
            meter.release("missing", "failed")

        meter.reserve("finalized", "a", "cost", 1)
        meter.finalize("finalized", usage={})
        with self.assertRaises(UsageOperationStateError):
            meter.release("finalized", "too-late")

        meter.reserve("released", "b", "cost", 1)
        released = meter.release("released", "failed")
        self.assertEqual(meter.release("released", "different"), released)
        with self.assertRaises(UsageOperationStateError):
            meter.finalize("released", usage={})

    def test_upgrade_ratchets_snapshot_and_downgrade_is_deferred(self) -> None:
        meter = self.meter(plan=BASIC)
        meter.reserve("basic-op", "a", "article", 1)
        upgraded = self.meter(plan=PRO)
        upgraded.reserve("pro-op", "b", "chat", 1)
        downgraded = self.meter(plan=BASIC)
        downgraded.reserve("after-downgrade", "c", "chat", 1)

        month = self.usage.get_month(USER_ID, "2026-07")
        self.assertEqual(month["plan_id"], "pro")
        self.assertEqual(month["article_limit"], 20)
        self.assertEqual(month["chat_limit"], 40)
        self.assertEqual(month["cost_micro_usd_limit"], 10_000)
        self.assertEqual(month["sentences_per_article"], 200)
        self.assertEqual(month["source_tokens_per_article"], 48_000)

    def test_legacy_article_usage_is_enforced_by_first_reservation(self) -> None:
        self.usage.add(USER_ID, "2026-07", articles=BASIC.articles_per_month)
        meter = self.meter()

        with self.assertRaises(EntitlementError) as context:
            meter.reserve("legacy-blocked", "payload", "article", 0)

        self.assertEqual(context.exception.code, "article_quota_exceeded")
        month = self.usage.get_month(USER_ID, "2026-07")
        self.assertEqual(month["articles"], BASIC.articles_per_month)


class UsageSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.usage = JsonUsageRepository(root / "usage.json")
        self.subscriptions = JsonSubscriptionRepository(root / "subscriptions.json")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def guard(self, plan: PlanLimits) -> object:
        guard = build_guard(self.subscriptions, self.usage, USER_ID, NOW)
        guard.plan = plan
        return guard

    def test_summary_is_pending_aware_and_uses_exact_remaining(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=True,
        )
        meter.reserve("committed", "a", "article", 5)
        meter.finalize(
            "committed",
            usage={
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "actual_cost_micro_usd": 2,
            },
            result_ref="result",
        )
        meter.reserve("pending-article", "b", "article", 5)
        meter.reserve("pending-chat", "c", "chat", 5)

        summary = usage_summary(self.guard(BASIC))

        self.assertEqual(summary["articles_used"], 1)
        self.assertEqual(summary["articles_pending"], 1)
        self.assertEqual(summary["articles_remaining"], 3)
        self.assertEqual(summary["chats_used"], 0)
        self.assertEqual(summary["chats_pending"], 1)
        self.assertEqual(summary["chats_remaining"], 9)
        self.assertEqual(summary["reset_at"], "2026-08-01T00:00:00+00:00")

    def test_summary_warns_at_eighty_percent_without_exposing_hidden_usage(self) -> None:
        meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: BASIC,
            reservation_enabled=True,
        )
        for index in range(4):
            meter.reserve(f"article-{index}", str(index), "article", 10)

        summary = usage_summary(self.guard(BASIC))

        self.assertEqual(summary["warning_codes"], ["article_quota_approaching"])
        for hidden in (
            "tokens",
            "input_tokens",
            "output_tokens",
            "cost_micro_usd",
            "cost_micro_usd_limit",
        ):
            self.assertNotIn(hidden, summary)

    def test_current_billing_plan_can_differ_from_quota_snapshot(self) -> None:
        pinned = PlanLimits("pro", 20, 40, 321, 45_678, 10_000, 3_000_000)
        pro_meter = UsageMeter(
            self.subscriptions,
            self.usage,
            USER_ID,
            rate=RATE,
            now=NOW,
            plan_loader=lambda _: pinned,
            reservation_enabled=True,
        )
        pro_meter.reserve("pro-op", "a", "article", 1)

        summary = usage_summary(self.guard(BASIC))

        self.assertEqual(summary["plan"], "basic")
        self.assertEqual(summary["quota_plan"], "pro")
        self.assertEqual(summary["articles_limit"], 20)
        self.assertEqual(summary["chats_limit"], 40)
        self.assertEqual(summary["sentences_per_article"], pinned.sentences_per_article)
        self.assertEqual(summary["source_tokens_per_article"], pinned.source_tokens_per_article)

    def test_legacy_or_missing_month_is_safe(self) -> None:
        summary = usage_summary(self.guard(BASIC))

        self.assertEqual(summary["plan"], "basic")
        self.assertEqual(summary["quota_plan"], "basic")
        self.assertEqual(summary["articles_pending"], 0)
        self.assertEqual(summary["chats_pending"], 0)


if __name__ == "__main__":
    unittest.main()
