import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from accounts import BillingError, SubscriptionEvent, User
from accounts.billing import MockBillingProvider
from accounts.ports import (
    CheckoutDiscovery,
    CheckoutSession,
    HistoricalCheckout,
    ProviderSubscription,
)
from accounts.services import billing_flow
from accounts.storage import (
    InMemorySubscriptionRepository,
    JsonEmailAuthService,
    JsonSubscriptionRepository,
)
from accounts.testing import build_test_accounts
from core.pipeline import UsageTally
from core.plans import PLAN_CATALOG, PlanLimits, load_plans
from core.usage_costs import ModelRate
from deps import (
    get_accounts,
    get_page_preload_repository,
    get_subscription_repository,
    get_usage_repository,
)
from fastapi.testclient import TestClient
from main import app
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.usage_repository import JsonUsageRepository
from scripts.create_stripe_prices import PLANS as STRIPE_TEST_PLANS
from services.entitlements import (
    EntitlementError,
    build_guard,
    current_month,
    resolve_plan_id,
    usage_summary,
)
from services.usage_meter import UsageMeter

TINY_PLAN = PlanLimits(
    plan_id="basic",
    articles_per_month=2,
    chats_per_month=2,
    sentences_per_article=5,
    source_tokens_per_article=50,
    cost_micro_usd_per_month=1_000,
    tokens_per_month=100,
)


class PlanLimitTests(unittest.TestCase):
    def test_plan_limits_match_the_approved_launch_matrix(self):
        with patch.dict("os.environ", {}, clear=True):
            plans = load_plans()

        self.assertEqual(plans["basic"].articles_per_month, 3)
        self.assertEqual(plans["basic"].chats_per_month, 15)
        self.assertEqual(plans["basic"].sentences_per_article, 50)
        self.assertEqual(plans["basic"].source_tokens_per_article, 12_000)
        self.assertEqual(plans["basic"].cost_micro_usd_per_month, 200_000)
        self.assertEqual(plans["pro"].articles_per_month, 40)
        self.assertEqual(plans["pro"].chats_per_month, 400)
        self.assertEqual(plans["pro"].sentences_per_article, 150)
        self.assertEqual(plans["pro"].source_tokens_per_article, 36_000)
        self.assertEqual(plans["pro"].cost_micro_usd_per_month, 2_500_000)
        self.assertEqual(plans["max"].articles_per_month, 120)
        self.assertEqual(plans["max"].chats_per_month, 1_200)
        self.assertEqual(plans["max"].sentences_per_article, 300)
        self.assertEqual(plans["max"].source_tokens_per_article, 72_000)
        self.assertEqual(plans["max"].cost_micro_usd_per_month, 7_000_000)

    def test_stripe_test_prices_match_the_approved_pilot(self):
        self.assertEqual(
            STRIPE_TEST_PLANS,
            {
                "pro": ("Untangle Pro", 1480),
                "max": ("Untangle Max", 3980),
            },
        )

    def test_new_plan_limits_are_environment_overridable(self):
        overrides = {
            "PLAN_BASIC_SOURCE_TOKENS_PER_ARTICLE": "101",
            "PLAN_BASIC_COST_MICRO_USD_PER_MONTH": "102",
            "PLAN_PRO_SOURCE_TOKENS_PER_ARTICLE": "201",
            "PLAN_PRO_COST_MICRO_USD_PER_MONTH": "202",
            "PLAN_MAX_SOURCE_TOKENS_PER_ARTICLE": "301",
            "PLAN_MAX_COST_MICRO_USD_PER_MONTH": "302",
        }
        with patch.dict("os.environ", overrides, clear=True):
            plans = load_plans()

        self.assertEqual(plans["basic"].source_tokens_per_article, 101)
        self.assertEqual(plans["basic"].cost_micro_usd_per_month, 102)
        self.assertEqual(plans["pro"].source_tokens_per_article, 201)
        self.assertEqual(plans["pro"].cost_micro_usd_per_month, 202)
        self.assertEqual(plans["max"].source_tokens_per_article, 301)
        self.assertEqual(plans["max"].cost_micro_usd_per_month, 302)


class ResolvePlanTests(unittest.TestCase):
    def test_current_month_normalizes_aware_datetime_to_utc(self):
        local_time = datetime(2026, 8, 1, 0, 30, tzinfo=timezone(timedelta(hours=14)))
        self.assertEqual(current_month(local_time), "2026-07")

    def test_current_month_rejects_naive_datetime(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            current_month(datetime(2026, 7, 1))

    def test_no_subscription_is_basic(self):
        self.assertEqual(resolve_plan_id(None), "basic")

    def test_active_subscription_uses_its_plan(self):
        self.assertEqual(resolve_plan_id({"plan": "pro", "status": "active"}), "pro")

    def test_canceled_subscription_falls_back_to_basic(self):
        self.assertEqual(resolve_plan_id({"plan": "pro", "status": "canceled"}), "basic")

    def test_expired_period_falls_back_to_basic(self):
        now = datetime(2026, 7, 11, tzinfo=UTC)
        long_ago = int(datetime(2026, 5, 1, tzinfo=UTC).timestamp())
        record = {"plan": "max", "status": "active", "current_period_end": long_ago}
        self.assertEqual(resolve_plan_id(record, now), "basic")

    def test_period_within_grace_keeps_plan(self):
        now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
        recent = int(datetime(2026, 7, 11, 0, 0, tzinfo=UTC).timestamp())
        record = {"plan": "pro", "status": "active", "current_period_end": recent}
        self.assertEqual(resolve_plan_id(record, now), "pro")


class EntitlementGuardTests(unittest.TestCase):
    def test_explicit_zero_snapshot_limits_do_not_fall_back_to_plan(self):
        guard = self._guard()
        with patch.object(
            self.usage,
            "get_month",
            return_value={
                "user_id": "u1",
                "month": guard.month,
                "plan_id": "basic",
                "committed_articles": 0,
                "committed_chats": 0,
                "reserved_articles": 0,
                "reserved_chats": 0,
                "article_limit": 0,
                "chat_limit": 0,
            },
        ):
            summary = usage_summary(guard)

        self.assertEqual(summary["articles_limit"], 0)
        self.assertEqual(summary["chats_limit"], 0)

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.usage = JsonUsageRepository(tmp / "usage.json")
        self.subs = JsonSubscriptionRepository(tmp / "subs.json")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _guard(self):
        guard = build_guard(self.subs, self.usage, "u1")
        guard.plan = TINY_PLAN
        return guard

    def test_article_quota_blocks_at_limit(self):
        guard = self._guard()
        guard.check_article()
        guard.record_article(tokens=10)
        guard.record_article(tokens=10)
        with self.assertRaises(EntitlementError) as ctx:
            guard.check_article()
        self.assertEqual(ctx.exception.code, "article_quota_exceeded")
        self.assertEqual(ctx.exception.status_code, 402)

    def test_chat_quota_blocks_at_limit(self):
        guard = self._guard()
        guard.record_chat()
        guard.record_chat()
        with self.assertRaises(EntitlementError) as ctx:
            guard.check_chat()
        self.assertEqual(ctx.exception.code, "chat_quota_exceeded")

    def test_token_budget_blocks_even_with_articles_left(self):
        guard = self._guard()
        guard.record_article(tokens=150)  # over the 100-token budget
        with self.assertRaises(EntitlementError) as ctx:
            guard.check_article()
        self.assertEqual(ctx.exception.code, "token_budget_exceeded")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_usage_is_scoped_to_the_month(self):
        guard = self._guard()
        guard.record_article()
        other = self.usage.get_month("u1", "1999-01")
        self.assertEqual(other["articles"], 0)
        this = self.usage.get_month("u1", current_month())
        self.assertEqual(this["articles"], 1)


class UsageTallyTests(unittest.TestCase):
    def test_accumulates_reported_usage_and_tolerates_missing(self):
        class _Usage:
            total_tokens = 123

        class _WithUsage:
            usage = _Usage()

        class _WithoutUsage:
            pass

        tally = UsageTally()
        tally.add_response(_WithUsage())
        tally.add_response(_WithoutUsage())
        tally.add_response(_WithUsage())
        self.assertEqual(tally.total_tokens, 246)


class _StubProvider:
    def __init__(self, event):
        self._event = event

    def parse_webhook_event(self, payload, signature):
        subscription_id = self._event.data.get("stripe_subscription_id") or "sub_stub"
        derived_event_id = (
            f"evt_stub_{subscription_id}_{self._event.kind}_"
            f"{self._event.data.get('status')}_{self._event.data.get('cancel_at')}"
        )
        return replace(
            self._event,
            event_id=self._event.event_id or derived_event_id,
            data={**self._event.data, "stripe_subscription_id": subscription_id},
        )

    def retrieve_subscription(self, stripe_subscription_id):
        event = self.parse_webhook_event(b"", None)
        return ProviderSubscription(
            user_id=event.user_id or "u1",
            stripe_customer_id=event.stripe_customer_id or "cus_1",
            stripe_subscription_id=stripe_subscription_id,
            plan=event.data.get("plan") or "pro",
            status=event.data.get("status")
            or ("canceled" if event.kind == "deleted" else "active"),
            current_period_end=event.data.get("current_period_end") or 1_900_000_000,
            cancel_at=event.data.get("cancel_at"),
        )


class WebhookFlowTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.subs = JsonSubscriptionRepository(Path(self._tmpdir.name) / "subs.json")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_subscription_updated_applies_plan(self):
        event = SubscriptionEvent(
            kind="updated",
            user_id="u1",
            stripe_customer_id="cus_1",
            data={"plan": "pro", "status": "active", "current_period_end": 1900000000},
        )
        result = billing_flow.handle_webhook(self.subs, _StubProvider(event), b"{}", "sig")
        self.assertEqual(result, "applied")
        record = self.subs.get("u1")
        self.assertEqual(record["plan"], "pro")
        self.assertEqual(resolve_plan_id(record, datetime(2026, 7, 11, tzinfo=UTC)), "pro")

    def test_subscription_deleted_reverts_to_basic(self):
        self.subs.upsert("u1", {"plan": "pro", "status": "active", "stripe_customer_id": "cus_1"})
        event = SubscriptionEvent(kind="deleted", stripe_customer_id="cus_1", data={})
        result = billing_flow.handle_webhook(self.subs, _StubProvider(event), b"{}", "sig")
        self.assertEqual(result, "applied")
        self.assertEqual(resolve_plan_id(self.subs.get("u1")), "basic")

    def test_unmatched_customer_is_acknowledged_without_writes(self):
        event = SubscriptionEvent(kind="updated", stripe_customer_id="cus_unknown", data={})
        result = billing_flow.handle_webhook(self.subs, _StubProvider(event), b"{}", "sig")
        self.assertEqual(result, "unmatched")


class _LifecycleProvider:
    def __init__(self, event, snapshots):
        self.event = event
        self.snapshots = list(snapshots)
        self.retrievals = 0

    def parse_webhook_event(self, payload, signature):
        return self.event

    def retrieve_subscription(self, stripe_subscription_id):
        self.retrievals += 1
        snapshot = self.snapshots[min(self.retrievals - 1, len(self.snapshots) - 1)]
        self.last_subscription_id = stripe_subscription_id
        return snapshot


class AuthoritativeWebhookReconciliationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.subs = JsonSubscriptionRepository(Path(self._tmpdir.name) / "subs.json")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _event(self, event_id, subscription_id="sub_1"):
        return SubscriptionEvent(
            kind="updated",
            event_id=event_id,
            user_id="u1",
            stripe_customer_id="cus_1",
            data={"stripe_subscription_id": subscription_id},
        )

    @staticmethod
    def _snapshot(*, plan="pro", status="active", subscription_id="sub_1", customer="cus_1"):
        return ProviderSubscription(
            user_id="u1",
            stripe_customer_id=customer,
            stripe_subscription_id=subscription_id,
            plan=plan,
            status=status,
            current_period_end=1_900_000_000,
        )

    def test_deletion_then_old_active_event_keeps_authoritative_cancellation(self):
        deleted = _LifecycleProvider(
            self._event("evt_deleted"), [self._snapshot(status="canceled")]
        )
        billing_flow.handle_webhook(self.subs, deleted, b"{}", "sig", plans=PLAN_CATALOG)
        old_active = _LifecycleProvider(
            self._event("evt_old_active"), [self._snapshot(status="canceled")]
        )
        billing_flow.handle_webhook(self.subs, old_active, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(self.subs.get("u1")["status"], "canceled")
        self.assertEqual(old_active.retrievals, 1)

    def test_upgrade_uses_current_provider_plan_instead_of_event_payload(self):
        event = self._event("evt_old_pro")
        event = replace(event, data={"stripe_subscription_id": "sub_1", "plan": "pro"})
        provider = _LifecycleProvider(event, [self._snapshot(plan="max")])

        billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(self.subs.get("u1")["plan"], "max")

    def test_duplicate_event_is_deduplicated_after_one_authoritative_retrieval(self):
        provider = _LifecycleProvider(self._event("evt_once"), [self._snapshot()])

        self.assertEqual(
            billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG),
            "applied",
        )
        self.assertEqual(
            billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG),
            "duplicate",
        )
        self.assertEqual(provider.retrievals, 1)

    def test_customer_identity_conflict_fails_closed(self):
        provider = _LifecycleProvider(
            self._event("evt_conflict"),
            [self._snapshot(customer="cus_other")],
        )

        with self.assertRaises(BillingError) as context:
            billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)
        self.assertEqual(context.exception.status_code, 409)

    def test_legacy_snapshot_without_metadata_user_reconciles_through_matching_customer_index(self):
        self.subs.upsert("u1", {"stripe_customer_id": "cus_1"})
        provider = _LifecycleProvider(
            self._event("evt_legacy_index"),
            [replace(self._snapshot(), user_id=None)],
        )

        billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(self.subs.get("u1")["status"], "active")

    def test_checkout_completion_reference_binds_a_legacy_snapshot_without_metadata_user(self):
        event = replace(self._event("evt_checkout_completion"), kind="checkout_completed")
        provider = _LifecycleProvider(event, [replace(self._snapshot(), user_id=None)])

        billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(self.subs.get("u1")["stripe_customer_id"], "cus_1")

    def test_conflicting_legacy_snapshot_metadata_and_customer_index_fails_closed(self):
        self.subs.upsert("u1", {"stripe_customer_id": "cus_1"})
        provider = _LifecycleProvider(
            self._event("evt_legacy_metadata_conflict"),
            [replace(self._snapshot(), user_id="u2")],
        )

        with self.assertRaises(BillingError) as context:
            billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)
        self.assertEqual(context.exception.status_code, 409)

    def test_terminal_snapshot_without_plan_or_period_revokes_the_same_subscription(self):
        self.subs.upsert(
            "u1",
            {
                "plan": "pro",
                "status": "active",
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_1",
            },
        )
        provider = _LifecycleProvider(
            self._event("evt_terminal"),
            [replace(self._snapshot(plan=None, status="canceled"), current_period_end=None)],
        )

        billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)

        record = self.subs.get("u1")
        self.assertEqual(record["status"], "canceled")
        self.assertNotEqual(resolve_plan_id(record), "pro")

    def test_differing_nonterminal_subscription_cannot_replace_tracked_resource(self):
        for status in ("past_due", "paused", "incomplete", "unpaid", "unknown"):
            with self.subTest(status=status):
                self.subs.upsert(
                    "u1",
                    {
                        "plan": "pro",
                        "status": status,
                        "stripe_customer_id": "cus_1",
                        "stripe_subscription_id": "sub_tracked",
                    },
                )
                provider = _LifecycleProvider(
                    self._event(f"evt_{status}", subscription_id="sub_new"),
                    [self._snapshot(subscription_id="sub_new")],
                )

                with self.assertRaises(BillingError) as context:
                    billing_flow.handle_webhook(
                        self.subs,
                        provider,
                        b"{}",
                        "sig",
                        plans=PLAN_CATALOG,
                    )
                self.assertEqual(context.exception.status_code, 409)
                self.assertEqual(self.subs.get("u1")["stripe_subscription_id"], "sub_tracked")

    def test_unrelated_terminal_resource_cannot_replace_a_tracked_nonterminal_subscription(self):
        self.subs.upsert(
            "u1",
            {
                "plan": "pro",
                "status": "past_due",
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_tracked",
            },
        )
        provider = _LifecycleProvider(
            self._event("evt_unrelated_canceled", subscription_id="sub_old"),
            [replace(self._snapshot(subscription_id="sub_old", status="canceled"), plan=None)],
        )

        result = billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(result, "ignored_mismatch")
        self.assertEqual(self.subs.get("u1")["stripe_subscription_id"], "sub_tracked")

    def test_simultaneous_handlers_refresh_after_a_real_competing_cas(self):
        shared_state = InMemorySubscriptionRepository.shared_state()
        initial_retrieval_barrier = threading.Barrier(2)
        winner_committed = threading.Event()

        class _WinnerRepository(InMemorySubscriptionRepository):
            def compare_and_swap(self, user_id, record, *, expected_revision):
                persisted = super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )
                if persisted is not None:
                    winner_committed.set()
                return persisted

        class _LoserRepository(InMemorySubscriptionRepository):
            def __init__(self, state):
                super().__init__(state)
                self.first_write = True

            def compare_and_swap(self, user_id, record, *, expected_revision):
                if self.first_write:
                    self.first_write = False
                    if not winner_committed.wait(timeout=1):
                        raise AssertionError("winner did not commit before stale CAS")
                return super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )

        first_repository = _WinnerRepository(shared_state)
        second_repository = _LoserRepository(shared_state)

        class _BarrierProvider(_LifecycleProvider):
            def retrieve_subscription(self, stripe_subscription_id):
                if self.retrievals == 0:
                    try:
                        initial_retrieval_barrier.wait(timeout=1)
                    except threading.BrokenBarrierError as exc:
                        raise AssertionError("handlers did not reach initial retrieval") from exc
                return super().retrieve_subscription(stripe_subscription_id)

        first_provider = _BarrierProvider(
            self._event("evt_winner"),
            [replace(self._snapshot(status="canceled"), plan=None)],
        )
        second_provider = _BarrierProvider(
            self._event("evt_loser"),
            [
                self._snapshot(status="active"),
                replace(self._snapshot(status="canceled"), plan=None),
            ],
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda inputs: billing_flow.handle_webhook(
                        inputs[0],
                        inputs[1],
                        b"{}",
                        "sig",
                        plans=PLAN_CATALOG,
                    ),
                    (
                        (first_repository, first_provider),
                        (second_repository, second_provider),
                    ),
                )
            )

        self.assertEqual(results, ["applied", "applied"])
        self.assertEqual(first_provider.retrievals, 1)
        self.assertEqual(second_provider.retrievals, 2)
        self.assertEqual(first_repository.get("u1")["status"], "canceled")
        self.assertEqual(
            set(first_repository.get("u1")["processed_billing_events"]),
            {"evt_winner", "evt_loser"},
        )

    def test_evicted_event_replay_fetches_current_state_instead_of_using_old_payload(self):
        for index in range(billing_flow._EVENT_HISTORY_LIMIT + 1):
            provider = _LifecycleProvider(
                self._event(f"evt_{index}"),
                [self._snapshot()],
            )
            billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)
        processed = self.subs.get("u1")["processed_billing_events"]
        self.assertEqual(len(processed), billing_flow._EVENT_HISTORY_LIMIT)
        self.assertNotIn("evt_0", processed)

        provider = _LifecycleProvider(
            self._event("evt_0"),
            [replace(self._snapshot(status="canceled"), plan=None)],
        )

        billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(provider.retrievals, 1)
        self.assertEqual(self.subs.get("u1")["status"], "canceled")
        self.assertEqual(
            len(self.subs.get("u1")["processed_billing_events"]),
            billing_flow._EVENT_HISTORY_LIMIT,
        )

    def test_malformed_or_unsupported_active_snapshot_does_not_grant_access(self):
        for snapshot in (
            replace(self._snapshot(), plan=None),
            replace(self._snapshot(), current_period_end=True),
        ):
            with self.subTest(snapshot=snapshot):
                provider = _LifecycleProvider(self._event("evt_malformed"), [snapshot])

                with self.assertRaises(BillingError) as context:
                    billing_flow.handle_webhook(
                        self.subs,
                        provider,
                        b"{}",
                        "sig",
                        plans=PLAN_CATALOG,
                    )
                self.assertEqual(context.exception.status_code, 409)
                self.assertIsNone(self.subs.get("u1"))

    def test_cas_conflict_retrieves_a_fresh_provider_snapshot_before_commit(self):
        class _ConflictOnceRepository(JsonSubscriptionRepository):
            def __init__(self, path):
                super().__init__(path)
                self.conflicted = False

            def compare_and_swap(self, user_id, record, *, expected_revision):
                if not self.conflicted:
                    self.conflicted = True
                    return None
                return super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )

        repository = _ConflictOnceRepository(Path(self._tmpdir.name) / "conflict.json")
        provider = _LifecycleProvider(
            self._event("evt_conflict_retry"),
            [self._snapshot(plan="pro"), self._snapshot(plan="max")],
        )

        billing_flow.handle_webhook(repository, provider, b"{}", "sig", plans=PLAN_CATALOG)

        self.assertEqual(provider.retrievals, 2)
        self.assertEqual(repository.get("u1")["plan"], "max")

    def test_failed_persistence_returns_retryable_outcome_without_payload_merge(self):
        class _NeverPersistsRepository(JsonSubscriptionRepository):
            def compare_and_swap(self, user_id, record, *, expected_revision):
                return None

        repository = _NeverPersistsRepository(Path(self._tmpdir.name) / "failed.json")
        provider = _LifecycleProvider(self._event("evt_failed"), [self._snapshot()])

        with self.assertRaises(BillingError) as context:
            billing_flow.handle_webhook(repository, provider, b"{}", "sig", plans=PLAN_CATALOG)
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(repository.get("u1"), None)
        self.assertEqual(provider.retrievals, 3)

    def test_customer_index_conflict_fails_closed_without_writing_the_snapshot(self):
        self.subs.upsert("u2", {"stripe_customer_id": "cus_1"})
        provider = _LifecycleProvider(self._event("evt_index_conflict"), [self._snapshot()])

        with self.assertRaises(BillingError) as context:
            billing_flow.handle_webhook(self.subs, provider, b"{}", "sig", plans=PLAN_CATALOG)
        self.assertEqual(context.exception.status_code, 409)
        self.assertIsNone(self.subs.get("u1"))


class StripeWebhookSecurityTests(unittest.TestCase):
    def test_bad_signature_is_rejected(self):
        try:
            import stripe  # noqa: F401
            from accounts.billing import StripeBillingProvider
        except ImportError:
            self.skipTest("stripe package not installed")

        provider = StripeBillingProvider(
            secret_key="sk_test_dummy",
            webhook_secret="whsec_dummy",
            price_ids={"pro": "price_pro"},
        )
        with self.assertRaises(BillingError):
            provider.parse_webhook_event(b'{"type": "x"}', "t=1,v1=bad")
        with self.assertRaises(BillingError):
            provider.parse_webhook_event(b'{"type": "x"}', None)


class BillingApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        auth_service = JsonEmailAuthService(tmp / "users.json", tmp / "sessions.json")
        self.usage = JsonUsageRepository(tmp / "usage.json")
        self.subs = JsonSubscriptionRepository(tmp / "subs.json")
        preloads = JsonPagePreloadRepository(tmp / "preloads.json")
        accounts = build_test_accounts(
            plans=PLAN_CATALOG,
            auth_service=auth_service,
            subscription_repository=self.subs,
            billing_provider=MockBillingProvider(PLAN_CATALOG),
        )
        app.dependency_overrides[get_accounts] = lambda: accounts
        app.dependency_overrides[get_page_preload_repository] = lambda: preloads
        app.dependency_overrides[get_usage_repository] = lambda: self.usage
        app.dependency_overrides[get_subscription_repository] = lambda: self.subs
        self.client = TestClient(app, raise_server_exceptions=False)

        login = self.client.post("/auth/login", json={"credential": "mock:reader@example.com"})
        self.user_id = login.json()["user"]["id"]
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmpdir.cleanup()

    def test_billing_me_defaults_to_basic(self):
        response = self.client.get("/billing/me", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["plan"], "basic")
        self.assertEqual(body["quota_plan"], "basic")
        self.assertEqual(body["articles_used"], 0)
        self.assertEqual(body["articles_pending"], 0)
        self.assertEqual(body["articles_remaining"], body["articles_limit"])
        self.assertEqual(body["chats_pending"], 0)
        self.assertEqual(body["chats_remaining"], body["chats_limit"])
        self.assertRegex(body["reset_at"], r"^\d{4}-\d{2}-01T00:00:00\+00:00$")
        self.assertGreater(body["source_tokens_per_article"], 0)
        self.assertEqual(body["warning_codes"], [])
        self.assertGreater(body["articles_limit"], 0)
        self.assertNotIn("tokens", body)
        self.assertNotIn("cost_micro_usd", body)

    def test_billing_me_exposes_pending_warning_without_hidden_costs(self):
        plan = PlanLimits("basic", 10, 10, 50, 12_000, 1_000, 200_000)
        meter = UsageMeter(
            self.subs,
            self.usage,
            self.user_id,
            rate=ModelRate("test", 1, 1, "test-v1"),
            plan_loader=lambda _: plan,
            reservation_enabled=True,
        )
        for index in range(8):
            meter.reserve(f"pending-{index}", str(index), "article", 10)

        body = self.client.get("/billing/me", headers=self.headers).json()

        self.assertEqual(body["articles_used"], 0)
        self.assertEqual(body["articles_pending"], 8)
        self.assertEqual(body["articles_remaining"], 2)
        self.assertEqual(body["warning_codes"], ["article_quota_approaching"])
        for hidden in (
            "tokens",
            "input_tokens",
            "output_tokens",
            "cost_micro_usd",
            "cost_micro_usd_limit",
            "tokenizer_encoding",
        ):
            self.assertNotIn(hidden, body)

    def test_billing_me_uses_pinned_sentence_and_source_limits(self):
        pinned = PlanLimits("basic", 10, 50, 17, 1_234, 1_000, 200_000)
        meter = UsageMeter(
            self.subs,
            self.usage,
            self.user_id,
            rate=ModelRate("test", 1, 1, "test-v1"),
            plan_loader=lambda _: pinned,
            reservation_enabled=True,
        )
        meter.reserve("pinned-limits", "payload", "cost", 1)

        body = self.client.get("/billing/me", headers=self.headers).json()

        self.assertEqual(body["sentences_per_article"], 17)
        self.assertEqual(body["source_tokens_per_article"], 1_234)

    def test_mock_checkout_activates_plan_immediately(self):
        response = self.client.post("/billing/checkout", json={"plan": "pro"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["activated"])

        me = self.client.get("/billing/me", headers=self.headers).json()
        self.assertEqual(me["plan"], "pro")

    def test_checkout_rejects_unknown_plan(self):
        # The plan is validated against the catalog rather than by a
        # hard-coded pattern, so an unsellable plan is a 400, not a 422.
        response = self.client.post(
            "/billing/checkout", json={"plan": "basic"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_exhausted_article_quota_returns_402_with_code(self):
        month = current_month()
        # Fill straight to a huge number so any plan default is exceeded.
        self.usage.add(self.user_id, month, articles=10_000)
        response = self.client.post(
            "/pages/preload",
            json={"page_url": "https://example.com/a", "html": "<p>hello</p>"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["code"], "article_quota_exceeded")

    def test_exhausted_token_budget_returns_429(self):
        self.usage.add(self.user_id, current_month(), tokens=10_000_000_000)
        response = self.client.post(
            "/chat",
            json={"message": "hi", "context_label": "sentence", "context_text": "Hello."},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "token_budget_exceeded")

    def test_portal_without_subscription_is_404(self):
        response = self.client.post("/billing/portal", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_webhook_route_rejects_mock_provider(self):
        response = self.client.post("/billing/webhook", content=b"{}")
        self.assertEqual(response.status_code, 400)


class StripeProviderCustomerIdTests(unittest.TestCase):
    """Switching BILLING_PROVIDER from mock to stripe must tolerate records
    that still carry mock customer ids."""

    def _provider(self):
        from accounts.billing import StripeBillingProvider

        return StripeBillingProvider(
            secret_key="sk_test_dummy",
            webhook_secret="whsec_dummy",
            price_ids={"pro": "price_pro"},
        )

    def test_portal_rejects_mock_customer_id_with_404(self):
        provider = self._provider()
        with self.assertRaises(BillingError) as ctx:
            provider.create_portal_session("mock_customer_u1", return_url="http://x")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_checkout_ignores_mock_customer_id(self):
        create_session = Mock(return_value=SimpleNamespace(url="https://checkout.example/session"))
        stripe = SimpleNamespace(
            checkout=SimpleNamespace(Session=SimpleNamespace(create=create_session))
        )
        provider = self._provider()
        from accounts import User

        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            session = provider.create_checkout_session(
                User(id="u1", email="u1@example.com", display_name="U"),
                "pro",
                success_url="http://s",
                cancel_url="http://c",
                price_id="price_pro",
                stripe_customer_id="mock_customer_u1",
                customer_email="u1@example.com",
                idempotency_key="checkout-key",
                operation_id="019c0000-0000-7000-8000-000000000001",
            )

        self.assertEqual(session.url, "https://checkout.example/session")
        self.assertEqual(stripe.api_key, "sk_test_dummy")
        create_session.assert_called_once_with(
            mode="subscription",
            line_items=[{"price": "price_pro", "quantity": 1}],
            success_url="http://s",
            cancel_url="http://c",
            client_reference_id="u1",
            customer_email="u1@example.com",
            subscription_data={
                "metadata": {
                    "user_id": "u1",
                    "plan": "pro",
                    "checkout_operation_id": "019c0000-0000-7000-8000-000000000001",
                }
            },
            metadata={
                "user_id": "u1",
                "plan": "pro",
                "checkout_operation_id": "019c0000-0000-7000-8000-000000000001",
            },
            idempotency_key="checkout-key",
        )

    def test_discovery_normalizes_all_identity_evidence_across_pages(self):
        first_session = SimpleNamespace(
            id="cs_first",
            url="https://checkout.example/first",
            status="open",
            metadata={
                "user_id": "u1",
                "plan": "pro",
                "checkout_operation_id": "op-first",
            },
            client_reference_id="u1",
            customer="cus_u1",
            customer_details=SimpleNamespace(email="u1@example.com"),
            line_items=SimpleNamespace(
                data=[SimpleNamespace(price=SimpleNamespace(id="price_pro"))]
            ),
            success_url="https://app.example/success",
            cancel_url="https://app.example/cancel",
            subscription=None,
            expires_at=1_900_000_000,
        )
        second_session = {
            "id": "cs_second",
            "url": "https://checkout.example/second",
            "status": "open",
            "metadata": {
                "user_id": "u1",
                "plan": "pro",
                "checkout_operation_id": "op-second",
            },
            "client_reference_id": "u1",
            "customer": "cus_u1",
            "customer_email": "u1@example.com",
            "line_items": {"data": [{"price": {"id": "price_pro"}}]},
            "success_url": "https://app.example/success",
            "cancel_url": "https://app.example/cancel",
        }
        list_sessions = Mock(
            side_effect=(
                SimpleNamespace(data=[first_session], has_more=True),
                {"data": [second_session], "has_more": False},
            )
        )
        stripe = SimpleNamespace(
            checkout=SimpleNamespace(Session=SimpleNamespace(list=list_sessions)),
            Subscription=SimpleNamespace(retrieve=Mock()),
        )

        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            discovery = self._provider().discover_checkout_sessions(
                User(id="u1", email="u1@example.com", display_name="U"),
                stripe_customer_id="cus_u1",
            )

        self.assertTrue(discovery.complete)
        self.assertEqual(
            [checkout.operation_id for checkout in discovery.sessions],
            ["op-first", "op-second"],
        )
        self.assertEqual(
            [
                (
                    checkout.metadata_user_id,
                    checkout.client_reference_id,
                    checkout.stripe_customer_id,
                )
                for checkout in discovery.sessions
            ],
            [("u1", "u1", "cus_u1"), ("u1", "u1", "cus_u1")],
        )
        self.assertEqual(
            list_sessions.call_args_list,
            [
                call(limit=100, expand=["data.line_items"]),
                call(
                    limit=100,
                    expand=["data.line_items"],
                    starting_after="cs_first",
                ),
            ],
        )

    def test_discovery_loads_status_for_an_expired_checkout_subscription(self):
        list_sessions = Mock(
            return_value={
                "data": [
                    {
                        "id": "cs_expired",
                        "status": "expired",
                        "metadata": {"user_id": "u1"},
                        "client_reference_id": "u1",
                        "subscription": "sub_active",
                    }
                ],
                "has_more": False,
            }
        )
        retrieve_subscription = Mock(return_value={"status": "active"})
        stripe = SimpleNamespace(
            checkout=SimpleNamespace(Session=SimpleNamespace(list=list_sessions)),
            Subscription=SimpleNamespace(retrieve=retrieve_subscription),
        )

        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            discovery = self._provider().discover_checkout_sessions(
                User(id="u1", email="u1@example.com", display_name="U"),
                stripe_customer_id=None,
            )

        self.assertEqual(discovery.sessions[0].stripe_subscription_id, "sub_active")
        self.assertEqual(discovery.sessions[0].subscription_status, "active")
        retrieve_subscription.assert_called_once_with("sub_active")

    def test_current_subscription_normalizes_sdk_fields_for_authoritative_reconciliation(self):
        retrieve = Mock(
            return_value=SimpleNamespace(
                id="sub_1",
                customer="cus_1",
                metadata={"user_id": "u1"},
                status="active",
                current_period_end=None,
                cancel_at=None,
                items=SimpleNamespace(
                    data=[
                        SimpleNamespace(
                            price=SimpleNamespace(id="price_pro"),
                            current_period_end=1_900_000_000,
                        )
                    ]
                ),
            )
        )
        stripe = SimpleNamespace(Subscription=SimpleNamespace(retrieve=retrieve))

        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            snapshot = self._provider().retrieve_subscription("sub_1")

        self.assertEqual(snapshot.user_id, "u1")
        self.assertEqual(snapshot.plan, "pro")
        self.assertEqual(snapshot.current_period_end, 1_900_000_000)
        retrieve.assert_called_once_with("sub_1", expand=["items.data.price"])

    def test_pending_idempotency_replay_keeps_the_complete_a_request_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonSubscriptionRepository(Path(directory) / "subscriptions.json")
            repository.upsert(
                "u1",
                {
                    "pending_checkout": {
                        "operation_id": "019c0000-0000-7000-8000-000000000001",
                        "user_id": "u1",
                        "requested_plan": "pro",
                        "price_id": "price_pro",
                        "success_url": "https://app.example/success",
                        "cancel_url": "https://app.example/cancel",
                        "stripe_customer_id": None,
                        "customer_choice": "email",
                        "email": "u1@example.com",
                        "idempotency_key": "legacy-key",
                        "state": "attempted",
                        "creation_attempted_at": 1_900_000_000,
                    }
                },
            )
            create_session = Mock(
                return_value=SimpleNamespace(url="https://checkout.example", id="cs_legacy")
            )
            stripe = SimpleNamespace(
                checkout=SimpleNamespace(Session=SimpleNamespace(create=create_session))
            )
            provider = self._provider()

            with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
                billing_flow.start_checkout(
                    repository,
                    provider,
                    PLAN_CATALOG,
                    User(id="u1", email="u1@example.com", display_name="U"),
                    "pro",
                    success_url="https://app.example/success",
                    cancel_url="https://app.example/cancel",
                )

            self.assertEqual(
                create_session.call_args.kwargs,
                {
                    "mode": "subscription",
                    "line_items": [{"price": "price_pro", "quantity": 1}],
                    "success_url": "https://app.example/success",
                    "cancel_url": "https://app.example/cancel",
                    "client_reference_id": "u1",
                    "customer_email": "u1@example.com",
                    "subscription_data": {
                        "metadata": {
                            "user_id": "u1",
                            "plan": "pro",
                            "checkout_operation_id": "019c0000-0000-7000-8000-000000000001",
                        }
                    },
                    "metadata": {
                        "user_id": "u1",
                        "plan": "pro",
                        "checkout_operation_id": "019c0000-0000-7000-8000-000000000001",
                    },
                    "idempotency_key": "legacy-key",
                },
            )

    def test_checkout_completion_preserves_verified_reference_and_customer_identity(self):
        stripe = SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=Mock()),
        )
        payload = (
            b'{"id":"evt_checkout","type":"checkout.session.completed","data":{"object":'
            b'{"payment_status":"paid","client_reference_id":"u1","customer":"cus_1",'
            b'"subscription":"sub_1","metadata":{"user_id":"u1","plan":"pro"}}}}'
        )
        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            event = self._provider().parse_webhook_event(payload, "sig")

        self.assertEqual(event.kind, "checkout_completed")
        self.assertEqual(event.user_id, "u1")
        self.assertEqual(event.stripe_customer_id, "cus_1")
        self.assertEqual(event.data["stripe_subscription_id"], "sub_1")

    def test_checkout_completion_rejects_conflicting_reference_and_metadata_identity(self):
        stripe = SimpleNamespace(
            Webhook=SimpleNamespace(construct_event=Mock()),
        )
        payload = (
            b'{"id":"evt_checkout","type":"checkout.session.completed","data":{"object":'
            b'{"payment_status":"paid","client_reference_id":"u1","customer":"cus_1",'
            b'"subscription":"sub_1","metadata":{"user_id":"u2"}}}}'
        )
        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            with self.assertRaises(BillingError):
                self._provider().parse_webhook_event(payload, "sig")


class _PendingCheckoutProvider:
    """Deterministic provider double for checkout-ownership regressions."""

    def __init__(self, *, discovery: CheckoutDiscovery | None = None) -> None:
        self._discovery = discovery or CheckoutDiscovery(sessions=(), complete=True)
        self._lock = threading.Lock()
        self.calls: list[dict[str, object]] = []
        self._sessions_by_key: dict[str, CheckoutSession] = {}
        self.fail_next_create = False
        self.on_create = None
        self.discovery_factory = None

    def checkout_price_id(self, plan_id: str) -> str:
        return f"price_{plan_id}"

    def discover_checkout_sessions(
        self, user: User, *, stripe_customer_id: str | None
    ) -> CheckoutDiscovery:
        if self.discovery_factory:
            return self.discovery_factory(user, stripe_customer_id)
        if self.calls:
            call = self.calls[-1]
            session = self._sessions_by_key[call["idempotency_key"]]
            return CheckoutDiscovery(
                sessions=(
                    HistoricalCheckout(
                        stripe_checkout_session_id=session.stripe_checkout_session_id,
                        url=session.url,
                        state="open",
                        user_id=user.id,
                        metadata_user_id=user.id,
                        client_reference_id=user.id,
                        operation_id=call["operation_id"],
                        requested_plan=call["plan_id"],
                        price_id=call["price_id"],
                        success_url=call["success_url"],
                        cancel_url=call["cancel_url"],
                        stripe_customer_id=call["stripe_customer_id"],
                    ),
                ),
                complete=True,
            )
        return self._discovery

    def create_checkout_session(
        self,
        user: User,
        plan_id: str,
        *,
        success_url: str,
        cancel_url: str,
        price_id: str,
        stripe_customer_id: str | None = None,
        customer_email: str,
        idempotency_key: str,
        operation_id: str,
    ) -> CheckoutSession:
        with self._lock:
            self.calls.append(
                {
                    "user_id": user.id,
                    "plan_id": plan_id,
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "price_id": price_id,
                    "stripe_customer_id": stripe_customer_id,
                    "customer_email": customer_email,
                    "idempotency_key": idempotency_key,
                    "operation_id": operation_id,
                }
            )
            if self.fail_next_create:
                self.fail_next_create = False
                raise BillingError("provider timeout", status_code=502)
            session = self._sessions_by_key.setdefault(
                idempotency_key,
                CheckoutSession(
                    url=f"https://checkout.example/{operation_id}",
                    stripe_checkout_session_id=f"cs_{operation_id}",
                ),
            )
            if self.on_create:
                self.on_create()
            return session

    def create_portal_session(self, stripe_customer_id: str, *, return_url: str) -> str:
        return return_url

    def parse_webhook_event(self, payload: bytes, signature: str | None) -> SubscriptionEvent:
        raise AssertionError("not used by checkout tests")


class PendingCheckoutOwnershipTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "subscriptions.json"
        self.user = User(id="user-1", email="reader@example.test", display_name="Reader")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _start(self, repository, provider, plan_id="pro"):
        return billing_flow.start_checkout(
            repository,
            provider,
            PLAN_CATALOG,
            self.user,
            plan_id,
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )

    def test_reuses_a_durable_pending_operation_and_its_provider_parameters(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()

        first = self._start(repository, provider)
        second = self._start(repository, provider)

        self.assertEqual(first, second)
        self.assertEqual(len(provider.calls), 1)
        pending = repository.get(self.user.id)["pending_checkout"]
        self.assertEqual(pending["state"], "created")
        self.assertEqual(pending["requested_plan"], "pro")
        self.assertEqual(pending["price_id"], "price_pro")
        self.assertEqual(pending["stripe_checkout_session_id"], first.stripe_checkout_session_id)
        self.assertEqual(pending["idempotency_key"], provider.calls[0]["idempotency_key"])

    def test_conflicting_plan_cannot_replace_an_unresolved_operation(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()
        self._start(repository, provider)

        with self.assertRaises(BillingError) as context:
            self._start(repository, provider, "max")

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(repository.get(self.user.id)["pending_checkout"]["requested_plan"], "pro")

    def test_retry_after_provider_timeout_keeps_the_creation_marker_and_idempotency_key(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()
        provider.fail_next_create = True

        with self.assertRaises(BillingError):
            self._start(repository, provider)

        attempted = repository.get(self.user.id)["pending_checkout"]
        self.assertEqual(attempted["state"], "attempted")
        recovered = self._start(repository, provider)

        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0]["idempotency_key"], provider.calls[1]["idempotency_key"])
        self.assertEqual(
            recovered.stripe_checkout_session_id,
            attempted.get("stripe_checkout_session_id") or recovered.stripe_checkout_session_id,
        )

    def test_retry_uses_saved_price_when_stripe_configuration_changes(self):
        from accounts.billing import StripeBillingProvider

        create_session = Mock(
            side_effect=(
                RuntimeError("timeout"),
                SimpleNamespace(
                    url="https://checkout.example/recovered",
                    id="cs_recovered",
                    expires_at=None,
                ),
            )
        )
        stripe = SimpleNamespace(
            checkout=SimpleNamespace(
                Session=SimpleNamespace(
                    create=create_session,
                    list=Mock(return_value={"data": [], "has_more": False}),
                )
            )
        )
        provider = StripeBillingProvider(
            secret_key="sk_test_dummy",
            webhook_secret="whsec_dummy",
            price_ids={"pro": "price_original"},
        )
        repository = JsonSubscriptionRepository(self.path)

        with patch("accounts.billing.stripe_billing._import_stripe", return_value=stripe):
            with self.assertRaises(BillingError):
                self._start(repository, provider)
            provider._price_ids["pro"] = "price_changed"
            self._start(repository, provider)

        self.assertEqual(
            [call.kwargs["line_items"][0]["price"] for call in create_session.call_args_list],
            ["price_original", "price_original"],
        )

    def test_retry_keeps_the_original_email_and_legacy_upsert_cannot_restore_stale_evidence(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()
        provider.fail_next_create = True
        with self.assertRaises(BillingError):
            self._start(repository, provider)
        stale_attempt = repository.get(self.user.id)
        self.user = self.user.model_copy(update={"email": "renamed@example.test"})

        self._start(repository, provider)
        repository.upsert(self.user.id, stale_attempt)

        pending = repository.get(self.user.id)["pending_checkout"]
        self.assertEqual(provider.calls[-1]["customer_email"], "reader@example.test")
        self.assertEqual(pending["state"], "created")
        self.assertIsNotNone(pending["stripe_checkout_session_id"])

    def test_legacy_upserts_preserve_pending_evidence_for_json_and_memory(self):
        pending = {
            "operation_id": "op-1",
            "user_id": self.user.id,
            "requested_plan": "pro",
            "price_id": "price_pro",
            "success_url": "https://app.example/success",
            "cancel_url": "https://app.example/cancel",
            "stripe_customer_id": None,
            "customer_choice": "email",
            "email": self.user.email,
            "idempotency_key": "key-1",
            "operation_metadata": {"operation_id": "op-1"},
            "state": "reserved",
        }
        repositories = (
            JsonSubscriptionRepository(self.path),
            InMemorySubscriptionRepository(),
        )
        for repository in repositories:
            stale = repository.upsert(self.user.id, {"pending_checkout": pending})
            advanced = repository.compare_and_swap(
                self.user.id,
                {
                    "pending_checkout": {
                        **pending,
                        "state": "attempted",
                        "creation_attempted_at": 1,
                    }
                },
                expected_revision=stale["revision"],
            )
            self.assertIsNotNone(advanced)
            repository.upsert(self.user.id, stale)
            current = repository.get(self.user.id)
            self.assertEqual(current["pending_checkout"]["state"], "attempted")
            self.assertEqual(current["pending_checkout"]["creation_attempted_at"], 1)
            with self.assertRaises(ValueError):
                repository.compare_and_swap(
                    self.user.id,
                    {"pending_checkout": pending},
                    expected_revision=current["revision"],
                )

    def test_proven_terminal_operation_can_be_replaced_but_missing_operation_history_cannot(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()
        self._start(repository, provider)
        first_pending = repository.get(self.user.id)["pending_checkout"]

        def terminal_history(_user, _customer):
            return CheckoutDiscovery(
                sessions=(
                    HistoricalCheckout(
                        stripe_checkout_session_id=first_pending["stripe_checkout_session_id"],
                        url=first_pending["url"],
                        state="complete",
                        user_id=self.user.id,
                        metadata_user_id=self.user.id,
                        client_reference_id=self.user.id,
                        operation_id=first_pending["operation_id"],
                        requested_plan="pro",
                        price_id="price_pro",
                        success_url="https://app.example/billing/done?state=success",
                        cancel_url="https://app.example/billing/done?state=cancel",
                        subscription_status="canceled",
                    ),
                ),
                complete=True,
            )

        provider.discovery_factory = terminal_history
        self._start(repository, provider)
        replacement = repository.get(self.user.id)["pending_checkout"]
        self.assertNotEqual(replacement["operation_id"], first_pending["operation_id"])

        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(), complete=True
        )
        with self.assertRaises(BillingError) as context:
            self._start(repository, provider)
        self.assertEqual(context.exception.status_code, 409)

    def test_adopted_terminal_history_is_reconciled_before_replacement(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_adopted",
            url="https://checkout.example/adopted",
            state="open",
            user_id=self.user.id,
            metadata_user_id=self.user.id,
            client_reference_id=self.user.id,
            operation_id="op_historical",
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )
        repository = JsonSubscriptionRepository(self.path)
        self._start(repository, provider)
        adopted = repository.get(self.user.id)["pending_checkout"]

        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(
                HistoricalCheckout(
                    **{
                        **historical.__dict__,
                        "state": "expired",
                        "url": None,
                    }
                ),
            ),
            complete=True,
        )
        self._start(repository, provider)

        replacement = repository.get(self.user.id)["pending_checkout"]
        self.assertNotEqual(replacement["operation_id"], adopted["operation_id"])
        self.assertEqual(len(provider.calls), 1)

    def test_legacy_adopted_checkout_reuses_then_replaces_after_proven_expiry(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_legacy",
            url="https://checkout.example/legacy",
            state="open",
            user_id=self.user.id,
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )
        repository = JsonSubscriptionRepository(self.path)
        adopted_session = self._start(repository, provider)
        reused_session = self._start(repository, provider)
        self.assertEqual(reused_session, adopted_session)

        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(
                HistoricalCheckout(
                    **{
                        **historical.__dict__,
                        "state": "expired",
                        "url": None,
                    }
                ),
            ),
            complete=True,
        )
        replacement = self._start(repository, provider)

        self.assertNotEqual(replacement.stripe_checkout_session_id, "cs_legacy")
        self.assertEqual(len(provider.calls), 1)

    def test_adopted_checkout_history_mismatch_fails_closed(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_adopted",
            url="https://checkout.example/adopted",
            state="open",
            user_id=self.user.id,
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )
        repository = JsonSubscriptionRepository(self.path)
        self._start(repository, provider)
        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(
                HistoricalCheckout(
                    **{
                        **historical.__dict__,
                        "stripe_checkout_session_id": "cs_replaced",
                    }
                ),
            ),
            complete=True,
        )

        with self.assertRaises(BillingError) as context:
            self._start(repository, provider)
        self.assertEqual(context.exception.status_code, 409)

    def test_adopted_checkout_does_not_ignore_another_open_session(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_saved",
            url="https://checkout.example/saved",
            state="open",
            user_id=self.user.id,
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )
        repository = JsonSubscriptionRepository(self.path)
        self._start(repository, provider)
        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(
                historical,
                HistoricalCheckout(
                    **{
                        **historical.__dict__,
                        "stripe_checkout_session_id": "cs_other_open",
                        "url": "https://checkout.example/other",
                    }
                ),
            ),
            complete=True,
        )

        with self.assertRaises(BillingError) as context:
            self._start(repository, provider)
        self.assertEqual(context.exception.status_code, 409)

    def test_terminal_adopted_session_cannot_replace_while_another_subscription_is_active(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_saved",
            url="https://checkout.example/saved",
            state="open",
            user_id=self.user.id,
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )
        repository = JsonSubscriptionRepository(self.path)
        self._start(repository, provider)
        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(
                HistoricalCheckout(
                    **{
                        **historical.__dict__,
                        "state": "expired",
                        "url": None,
                    }
                ),
                HistoricalCheckout(
                    **{
                        **historical.__dict__,
                        "stripe_checkout_session_id": "cs_other_complete",
                        "state": "complete",
                        "url": None,
                        "stripe_subscription_id": "sub_active",
                        "subscription_status": "active",
                    }
                ),
            ),
            complete=True,
        )

        with self.assertRaises(BillingError) as context:
            self._start(repository, provider)
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(provider.calls, [])

    def test_concurrent_adapters_share_one_operation_and_provider_idempotency_key(self):
        provider = _PendingCheckoutProvider()
        first_repository = JsonSubscriptionRepository(self.path)
        second_repository = JsonSubscriptionRepository(self.path)

        with ThreadPoolExecutor(max_workers=2) as executor:
            sessions = list(
                executor.map(
                    lambda repository: self._start(repository, provider),
                    (first_repository, second_repository),
                )
            )

        self.assertEqual(sessions[0], sessions[1])
        self.assertEqual(
            {call["idempotency_key"] for call in provider.calls},
            {first_repository.get(self.user.id)["pending_checkout"]["idempotency_key"]},
        )

    def test_compatible_historical_open_checkout_is_adopted_without_creation(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_historical",
            url="https://checkout.example/historical",
            state="open",
            user_id="user-1",
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )

        session = self._start(JsonSubscriptionRepository(self.path), provider)

        self.assertEqual(session.stripe_checkout_session_id, "cs_historical")
        self.assertEqual(provider.calls, [])

    def test_partial_or_email_only_history_fails_closed_before_creation(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_email_only",
            url="https://checkout.example/email-only",
            state="open",
            email=self.user.email,
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=False)
        )

        with self.assertRaises(BillingError) as context:
            self._start(JsonSubscriptionRepository(self.path), provider)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(provider.calls, [])

    def test_disagreeing_identity_or_known_customer_evidence_fails_closed(self):
        disagreement = HistoricalCheckout(
            stripe_checkout_session_id="cs_disagreement",
            url="https://checkout.example/disagreement",
            state="open",
            user_id=self.user.id,
            metadata_user_id=self.user.id,
            client_reference_id="other-user",
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(disagreement,), complete=True)
        )
        with self.assertRaises(BillingError) as context:
            self._start(JsonSubscriptionRepository(self.path), provider)
        self.assertEqual(context.exception.status_code, 409)

        self.path.unlink(missing_ok=True)
        repository = JsonSubscriptionRepository(self.path)
        repository.upsert(self.user.id, {"stripe_customer_id": "cus_known"})
        missing_customer = HistoricalCheckout(
            stripe_checkout_session_id="cs_missing-customer",
            url="https://checkout.example/missing-customer",
            state="open",
            user_id=self.user.id,
            metadata_user_id=self.user.id,
            client_reference_id=self.user.id,
            requested_plan="pro",
            price_id="price_pro",
            success_url="https://app.example/billing/done?state=success",
            cancel_url="https://app.example/billing/done?state=cancel",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(missing_customer,), complete=True)
        )
        with self.assertRaises(BillingError) as context:
            self._start(repository, provider)
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(provider.calls, [])

    def test_expired_checkout_with_an_active_subscription_fails_closed(self):
        historical = HistoricalCheckout(
            stripe_checkout_session_id="cs_expired",
            url=None,
            state="expired",
            user_id=self.user.id,
            metadata_user_id=self.user.id,
            client_reference_id=self.user.id,
            stripe_subscription_id="sub_active",
            subscription_status="active",
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(historical,), complete=True)
        )

        with self.assertRaises(BillingError) as context:
            self._start(JsonSubscriptionRepository(self.path), provider)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(provider.calls, [])

    def test_email_only_or_multiple_open_history_fails_closed_before_creation(self):
        email_only = HistoricalCheckout(
            stripe_checkout_session_id="cs_email_only",
            url="https://checkout.example/email-only",
            state="open",
            email=self.user.email,
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(email_only,), complete=True)
        )
        with self.assertRaises(BillingError) as context:
            self._start(JsonSubscriptionRepository(self.path), provider)
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(provider.calls, [])

        self.path.unlink(missing_ok=True)
        first_open = HistoricalCheckout(
            stripe_checkout_session_id="cs_first",
            url="https://checkout.example/first",
            state="open",
            user_id=self.user.id,
        )
        second_open = HistoricalCheckout(
            stripe_checkout_session_id="cs_second",
            url="https://checkout.example/second",
            state="open",
            user_id=self.user.id,
        )
        provider = _PendingCheckoutProvider(
            discovery=CheckoutDiscovery(sessions=(first_open, second_open), complete=True)
        )
        with self.assertRaises(BillingError) as context:
            self._start(JsonSubscriptionRepository(self.path), provider)
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(provider.calls, [])

    def test_expired_ambiguous_attempt_never_creates_again_when_history_is_empty(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()
        provider.fail_next_create = True
        with patch("accounts.services.billing_flow._now_epoch", return_value=1):
            with self.assertRaises(BillingError):
                self._start(repository, provider)
        provider.discovery_factory = lambda _user, _customer: CheckoutDiscovery(
            sessions=(), complete=True
        )

        with patch(
            "accounts.services.billing_flow._now_epoch",
            return_value=1 + billing_flow._CHECKOUT_KEY_RETENTION_SECONDS,
        ):
            with self.assertRaises(BillingError) as context:
                self._start(repository, provider)

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(len(provider.calls), 1)

    def test_webhook_interleaving_keeps_its_entitlement_when_checkout_completion_persists(self):
        repository = JsonSubscriptionRepository(self.path)
        provider = _PendingCheckoutProvider()

        def apply_webhook_snapshot():
            repository.upsert(
                self.user.id,
                {
                    "plan": "max",
                    "status": "active",
                    "stripe_customer_id": "cus_webhook",
                    "stripe_subscription_id": "sub_webhook",
                    "current_period_end": 1_900_000_000,
                },
            )

        provider.on_create = apply_webhook_snapshot
        self._start(repository, provider)

        record = repository.get(self.user.id)
        self.assertEqual(record["plan"], "max")
        self.assertEqual(record["stripe_subscription_id"], "sub_webhook")
        self.assertIn("pending_checkout", record)

    def test_customer_ownership_cannot_be_stolen_or_left_in_an_old_index(self):
        first_repository = JsonSubscriptionRepository(self.path)
        second_repository = JsonSubscriptionRepository(self.path)
        first_repository.upsert("user-1", {"stripe_customer_id": "cus_first"})

        with self.assertRaises(ValueError):
            second_repository.upsert("user-2", {"stripe_customer_id": "cus_first"})

        first_repository.upsert("user-1", {"stripe_customer_id": "cus_second"})
        self.assertIsNone(second_repository.find_user_by_customer("cus_first"))
        self.assertEqual(second_repository.find_user_by_customer("cus_second"), "user-1")


class CancelScheduleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.subs = JsonSubscriptionRepository(Path(self._tmpdir.name) / "subs.json")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_cancel_at_is_stored_and_cleared(self):
        base = {"plan": "pro", "status": "active", "current_period_end": 1900000000}
        scheduled = SubscriptionEvent(
            kind="updated",
            user_id="u1",
            stripe_customer_id="cus_1",
            data={**base, "cancel_at": 1900000000},
        )
        billing_flow.handle_webhook(self.subs, _StubProvider(scheduled), b"{}", "sig")
        self.assertEqual(self.subs.get("u1")["cancel_at"], 1900000000)

        # Resuming the subscription sends cancel_at=None, which must clear it.
        resumed = SubscriptionEvent(
            kind="updated",
            user_id="u1",
            stripe_customer_id="cus_1",
            data={**base, "cancel_at": None},
        )
        billing_flow.handle_webhook(self.subs, _StubProvider(resumed), b"{}", "sig")
        self.assertIsNone(self.subs.get("u1")["cancel_at"])


class PlanEndsAtApiTests(BillingApiTests):
    def test_billing_me_exposes_scheduled_cancellation(self):
        self.subs.upsert(
            self.user_id,
            {"plan": "pro", "status": "active", "cancel_at": 1900000000},
        )
        me = self.client.get("/billing/me", headers=self.headers).json()
        self.assertEqual(me["plan"], "pro")
        self.assertEqual(me["plan_ends_at"], 1900000000)

    def test_billing_me_has_no_end_date_without_cancellation(self):
        me = self.client.get("/billing/me", headers=self.headers).json()
        self.assertIsNone(me["plan_ends_at"])


class CheckoutPolicyTests(BillingApiTests):
    def test_checkout_rejected_while_paid_plan_is_active(self):
        # Stripe Checkout always creates a NEW subscription; a second one
        # would double-bill. Plan changes go through the portal.
        self.subs.upsert(self.user_id, {"plan": "pro", "status": "active"})
        response = self.client.post("/billing/checkout", json={"plan": "max"}, headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_checkout_allowed_again_after_cancellation(self):
        self.subs.upsert(self.user_id, {"plan": "pro", "status": "canceled"})
        response = self.client.post("/billing/checkout", json={"plan": "max"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)


class WebhookSubscriptionMatchTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.subs = JsonSubscriptionRepository(Path(self._tmpdir.name) / "subs.json")
        self.subs.upsert(
            "u1",
            {
                "plan": "max",
                "status": "active",
                "stripe_customer_id": "cus_1",
                "stripe_subscription_id": "sub_active",
            },
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_deleting_a_stale_subscription_keeps_the_active_plan(self):
        event = SubscriptionEvent(
            kind="deleted",
            stripe_customer_id="cus_1",
            data={"stripe_subscription_id": "sub_stale"},
        )
        result = billing_flow.handle_webhook(self.subs, _StubProvider(event), b"{}", "sig")
        self.assertEqual(result, "ignored_mismatch")
        self.assertEqual(resolve_plan_id(self.subs.get("u1")), "max")

    def test_deleting_the_active_subscription_cancels(self):
        event = SubscriptionEvent(
            kind="deleted",
            stripe_customer_id="cus_1",
            data={"stripe_subscription_id": "sub_active"},
        )
        billing_flow.handle_webhook(self.subs, _StubProvider(event), b"{}", "sig")
        self.assertEqual(resolve_plan_id(self.subs.get("u1")), "basic")

    def test_new_live_subscription_conflicts_with_another_live_record(self):
        event = SubscriptionEvent(
            kind="updated",
            stripe_customer_id="cus_1",
            data={
                "plan": "pro",
                "status": "active",
                "stripe_subscription_id": "sub_new",
                "current_period_end": 1900000000,
            },
        )
        with self.assertRaises(BillingError) as context:
            billing_flow.handle_webhook(self.subs, _StubProvider(event), b"{}", "sig")
        self.assertEqual(context.exception.status_code, 409)
        record = self.subs.get("u1")
        self.assertEqual(record["stripe_subscription_id"], "sub_active")
        self.assertEqual(record["plan"], "max")


class AnalyzeMeteringTests(BillingApiTests):
    def test_uncached_analyze_blocked_when_token_budget_exhausted(self):
        # No preload exists, so this would reach OpenAI; the token budget
        # must stop it first (selection analyses are token-metered).
        self.usage.add(self.user_id, current_month(), tokens=10_000_000_000)
        response = self.client.post(
            "/analyze",
            json={"text": "Some arbitrary sentence to analyze."},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "token_budget_exceeded")
