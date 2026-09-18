"""Contract tests for the shared `accounts` package.

Deliberately written against the package's own surface, with no Untangle
concepts in sight — the same cases hold in every application that embeds
it, so a copy of this file travels with the package.
"""

import unittest
from datetime import UTC, datetime

from accounts import (
    AccountsSettings,
    BillingError,
    PlanCatalog,
    SubscriptionEvent,
    build_accounts_container,
    read_bearer_token,
    resolve_plan_id,
)
from accounts.billing import MockBillingProvider, StripeBillingProvider
from accounts.identity import GoogleIdentityProvider, MockIdentityProvider
from accounts.ports import ProviderSubscription
from accounts.storage import InMemoryAuthService, InMemorySubscriptionRepository
from accounts.testing import build_test_accounts

PLANS = PlanCatalog(basic_plan_id="basic", paid_plan_ids=("pro", "max"))


class PlanCatalogTests(unittest.TestCase):
    def test_rejects_a_basic_plan_that_is_also_sold(self):
        with self.assertRaises(ValueError):
            PlanCatalog(basic_plan_id="pro", paid_plan_ids=("pro",))

    def test_lists_every_plan_id(self):
        self.assertEqual(PLANS.all_plan_ids, ("basic", "pro", "max"))

    def test_only_paid_plans_are_sellable(self):
        self.assertTrue(PLANS.is_paid("pro"))
        self.assertFalse(PLANS.is_paid("basic"))
        self.assertFalse(PLANS.is_paid(None))


class ResolvePlanIdTests(unittest.TestCase):
    def test_no_subscription_falls_back_to_basic(self):
        self.assertEqual(resolve_plan_id(None, PLANS), "basic")

    def test_inactive_status_falls_back_to_basic(self):
        record = {"plan": "pro", "status": "canceled"}
        self.assertEqual(resolve_plan_id(record, PLANS), "basic")

    def test_active_subscription_grants_its_plan(self):
        record = {
            "plan": "pro",
            "status": "active",
            "current_period_end": 1_900_000_000,
        }
        self.assertEqual(resolve_plan_id(record, PLANS), "pro")

    def test_active_subscription_without_a_finite_period_falls_back_to_basic(self):
        for period_end in (None, True, False, "1900000000", float("inf"), 0, -1):
            with self.subTest(period_end=period_end):
                record = {
                    "plan": "pro",
                    "status": "active",
                    "current_period_end": period_end,
                }
                self.assertEqual(resolve_plan_id(record, PLANS), "basic")

    def test_unknown_paid_plan_never_grants_access(self):
        record = {
            "plan": "unknown",
            "status": "trialing",
            "current_period_end": 1_900_000_000,
        }
        self.assertEqual(resolve_plan_id(record, PLANS), "basic")

    def test_mock_entitlement_requires_an_explicit_mock_mode(self):
        record = {
            "plan": "pro",
            "status": "active",
            "current_period_end": None,
            "entitlement_provider": "mock",
        }
        self.assertEqual(resolve_plan_id(record, PLANS), "basic")
        self.assertEqual(resolve_plan_id(record, PLANS, provider_mode="stripe"), "basic")
        self.assertEqual(resolve_plan_id(record, PLANS, provider_mode="mock"), "pro")

    def test_valid_finite_legacy_stripe_record_remains_compatible(self):
        now = datetime(2026, 9, 14, tzinfo=UTC)
        record = {
            "plan": "pro",
            "status": "active",
            "current_period_end": int(datetime(2026, 9, 15, tzinfo=UTC).timestamp()),
        }
        self.assertEqual(resolve_plan_id(record, PLANS, now), "pro")

    def test_long_expired_period_falls_back_even_while_marked_active(self):
        # A missed deletion webhook must not grant service forever.
        record = {"plan": "pro", "status": "active", "current_period_end": 1_000_000_000}
        self.assertEqual(resolve_plan_id(record, PLANS), "basic")


class BearerTokenTests(unittest.TestCase):
    def test_reads_a_bearer_header(self):
        self.assertEqual(read_bearer_token("Bearer abc"), "abc")

    def test_rejects_other_schemes_and_blanks(self):
        for header in (None, "", "abc", "Basic abc", "Bearer   "):
            self.assertIsNone(read_bearer_token(header), header)


class ProviderSelectionTests(unittest.TestCase):
    def _container(self, **settings):
        return build_accounts_container(AccountsSettings(**settings), plans=PLANS)

    def test_defaults_to_the_mock_providers(self):
        container = self._container()
        self.assertIsInstance(container.identity_provider, MockIdentityProvider)
        self.assertIsInstance(container.billing_provider, MockBillingProvider)

    def test_google_is_selected_by_configuration(self):
        container = self._container(auth_provider="google", google_oauth_client_id="id")
        self.assertIsInstance(container.identity_provider, GoogleIdentityProvider)

    def test_stripe_is_selected_by_configuration(self):
        container = self._container(billing_provider="stripe", stripe_secret_key="sk_test")
        self.assertIsInstance(container.billing_provider, StripeBillingProvider)

    def test_stripe_without_a_secret_key_fails_closed_at_startup(self):
        with self.assertRaises(ValueError):
            self._container(billing_provider="stripe")


class SignInTests(unittest.TestCase):
    def setUp(self):
        self.accounts = build_test_accounts(plans=PLANS)

    def test_login_issues_a_resolvable_session(self):
        session = self.accounts.login("mock:reader@example.com:Reader")
        self.assertEqual(session.user.email, "reader@example.com")
        self.assertEqual(session.user.display_name, "Reader")

        resolved = self.accounts.resolve_user(session.access_token)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, session.user.id)

    def test_signing_in_twice_reuses_the_account(self):
        first = self.accounts.login("mock:reader@example.com")
        second = self.accounts.login("mock:reader@example.com")
        self.assertEqual(first.user.id, second.user.id)
        self.assertNotEqual(first.access_token, second.access_token)

    def test_logout_invalidates_only_that_session(self):
        first = self.accounts.login("mock:reader@example.com")
        second = self.accounts.login("mock:reader@example.com")
        self.accounts.logout(first.access_token)
        self.assertIsNone(self.accounts.resolve_user(first.access_token))
        self.assertIsNotNone(self.accounts.resolve_user(second.access_token))


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.subscriptions = InMemorySubscriptionRepository()
        self.accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=self.subscriptions,
        )
        self.user = self.accounts.login("mock:buyer@example.com").user

    def test_mock_checkout_activates_the_plan_immediately(self):
        session = self.accounts.start_checkout(self.user, "pro")
        self.assertEqual(session.activated_plan, "pro")
        self.assertEqual(self.accounts.describe_subscription(self.user.id).plan, "pro")
        record = self.subscriptions.get(self.user.id)
        self.assertEqual(record["entitlement_provider"], "mock")
        self.assertEqual(record["pending_checkout"]["state"], "activated")
        self.assertEqual(
            record["stripe_customer_id"],
            record["pending_checkout"]["result_stripe_customer_id"],
        )
        self.assertEqual(
            self.accounts.open_portal(self.user),
            self.accounts.settings.billing_portal_return_url,
        )

    def test_mock_marker_cannot_grant_after_the_container_switches_to_stripe(self):
        self.subscriptions.upsert(
            self.user.id,
            {
                "plan": "pro",
                "status": "active",
                "entitlement_provider": "mock",
                "current_period_end": 1_900_000_000,
            },
        )
        stripe_accounts = build_accounts_container(
            AccountsSettings(billing_provider="stripe", stripe_secret_key="sk_test"),
            plans=PLANS,
            subscription_repository=self.subscriptions,
        )

        self.assertEqual(stripe_accounts.describe_subscription(self.user.id).plan, "basic")

    def test_mock_activation_recovers_after_a_revision_conflict_without_provider_replay(self):
        class _FailFirstActivationRepository(InMemorySubscriptionRepository):
            def __init__(self):
                super().__init__()
                self.failed_activation = False

            def compare_and_swap(self, user_id, record, *, expected_revision):
                pending = record.get("pending_checkout")
                if (
                    not self.failed_activation
                    and isinstance(pending, dict)
                    and pending.get("state") == "activated"
                ):
                    self.failed_activation = True
                    return None
                return super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )

        repository = _FailFirstActivationRepository()
        accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=repository,
        )
        user = accounts.login("mock:recovery@example.com").user

        session = accounts.start_checkout(user, "pro")

        self.assertTrue(repository.failed_activation)
        self.assertEqual(session.activated_plan, "pro")
        record = repository.get(user.id)
        self.assertEqual(record["pending_checkout"]["state"], "activated")
        self.assertEqual(record["entitlement_provider"], "mock")

    def test_terminal_mock_operation_is_replaced_instead_of_reactivated(self):
        first = self.accounts.start_checkout(self.user, "pro")
        first_operation = self.subscriptions.get(self.user.id)["pending_checkout"]["operation_id"]
        self.subscriptions.upsert(self.user.id, {"status": "canceled"})

        replacement = self.accounts.start_checkout(self.user, "pro")

        record = self.subscriptions.get(self.user.id)
        self.assertNotEqual(record["pending_checkout"]["operation_id"], first_operation)
        self.assertEqual(record["pending_checkout"]["state"], "activated")
        self.assertNotEqual(
            replacement.stripe_checkout_session_id, first.stripe_checkout_session_id
        )

    def test_cancellation_winning_during_mock_activation_cannot_activate_the_old_operation(self):
        class _CancelDuringActivationRepository(InMemorySubscriptionRepository):
            def __init__(self):
                super().__init__()
                self.canceled = False

            def compare_and_swap(self, user_id, record, *, expected_revision):
                pending = record.get("pending_checkout")
                if (
                    not self.canceled
                    and isinstance(pending, dict)
                    and pending.get("state") == "activated"
                ):
                    self.canceled = True
                    current = self.get(user_id) or {}
                    super().compare_and_swap(
                        user_id,
                        {**current, "status": "canceled"},
                        expected_revision=current["revision"],
                    )
                    return None
                return super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )

        repository = _CancelDuringActivationRepository()
        accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=repository,
        )
        user = accounts.login("mock:cancel@example.com").user

        with self.assertRaises(BillingError) as caught:
            accounts.start_checkout(user, "pro")

        self.assertEqual(caught.exception.status_code, 409)
        record = repository.get(user.id)
        self.assertTrue(repository.canceled)
        self.assertEqual(record["status"], "canceled")
        self.assertEqual(record["pending_checkout"]["state"], "terminal")
        self.assertNotIn("entitlement_provider", record)

    def test_cancellation_during_mock_provider_creation_fences_the_stale_activation(self):
        class _CancelOnceProvider(MockBillingProvider):
            def __init__(self, repository):
                super().__init__(PLANS)
                self.repository = repository
                self.canceled = False

            def create_checkout_session(self, user, plan_id, **kwargs):
                session = super().create_checkout_session(user, plan_id, **kwargs)
                if not self.canceled:
                    self.canceled = True
                    self.repository.upsert(user.id, {"status": "canceled"})
                return session

        repository = InMemorySubscriptionRepository()
        provider = _CancelOnceProvider(repository)
        accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=repository,
            billing_provider=provider,
        )
        user = accounts.login("mock:provider-cancel@example.com").user

        with self.assertRaises(BillingError) as caught:
            accounts.start_checkout(user, "pro")

        stale_operation = repository.get(user.id)["pending_checkout"]["operation_id"]
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(repository.get(user.id)["status"], "canceled")
        self.assertEqual(repository.get(user.id)["pending_checkout"]["state"], "terminal")
        self.assertNotIn("entitlement_provider", repository.get(user.id))

        accounts.start_checkout(user, "pro")
        replacement = repository.get(user.id)
        self.assertNotEqual(replacement["pending_checkout"]["operation_id"], stale_operation)
        self.assertEqual(replacement["pending_checkout"]["state"], "activated")

    def test_cancellation_after_mock_result_persistence_fences_the_stale_activation(self):
        class _CancelAfterCompletionRepository(InMemorySubscriptionRepository):
            def __init__(self):
                super().__init__()
                self.canceled = False

            def compare_and_swap(self, user_id, record, *, expected_revision):
                pending = record.get("pending_checkout")
                persisted = super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )
                if (
                    persisted is not None
                    and not self.canceled
                    and isinstance(pending, dict)
                    and pending.get("state") == "created"
                ):
                    self.canceled = True
                    current = self.get(user_id) or {}
                    super().compare_and_swap(
                        user_id,
                        {**current, "status": "canceled"},
                        expected_revision=current["revision"],
                    )
                return persisted

        repository = _CancelAfterCompletionRepository()
        accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=repository,
        )
        user = accounts.login("mock:completion-cancel@example.com").user

        with self.assertRaises(BillingError) as caught:
            accounts.start_checkout(user, "pro")

        stale_operation = repository.get(user.id)["pending_checkout"]["operation_id"]
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(repository.canceled)
        self.assertEqual(repository.get(user.id)["pending_checkout"]["state"], "terminal")

        accounts.start_checkout(user, "pro")
        replacement = repository.get(user.id)
        self.assertNotEqual(replacement["pending_checkout"]["operation_id"], stale_operation)
        self.assertEqual(replacement["pending_checkout"]["state"], "activated")

    def test_cancellation_before_mock_result_persistence_never_replays_the_old_operation(self):
        class _CancelBeforeCompletionRepository(InMemorySubscriptionRepository):
            def __init__(self):
                super().__init__()
                self.canceled = False

            def compare_and_swap(self, user_id, record, *, expected_revision):
                pending = record.get("pending_checkout")
                if (
                    not self.canceled
                    and isinstance(pending, dict)
                    and pending.get("state") == "created"
                ):
                    self.canceled = True
                    current = self.get(user_id) or {}
                    super().compare_and_swap(
                        user_id,
                        {**current, "status": "canceled"},
                        expected_revision=current["revision"],
                    )
                    return None
                return super().compare_and_swap(
                    user_id,
                    record,
                    expected_revision=expected_revision,
                )

        class _CountingMockProvider(MockBillingProvider):
            def __init__(self):
                super().__init__(PLANS)
                self.calls = 0

            def create_checkout_session(self, user, plan_id, **kwargs):
                self.calls += 1
                return super().create_checkout_session(user, plan_id, **kwargs)

        repository = _CancelBeforeCompletionRepository()
        provider = _CountingMockProvider()
        accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=repository,
            billing_provider=provider,
        )
        user = accounts.login("mock:before-completion-cancel@example.com").user

        with self.assertRaises(BillingError) as caught:
            accounts.start_checkout(user, "pro")

        record = repository.get(user.id)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(repository.canceled)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(record["pending_checkout"]["state"], "terminal")
        self.assertNotIn("entitlement_provider", record)

    def test_mock_checkout_evidence_cannot_be_reused_after_a_stripe_mode_switch(self):
        self.accounts.start_checkout(self.user, "pro")
        stripe_accounts = build_test_accounts(
            plans=PLANS,
            auth_service=InMemoryAuthService(),
            subscription_repository=self.subscriptions,
            billing_provider=MockBillingProvider(PLANS),
            settings=AccountsSettings(billing_provider="stripe", stripe_secret_key="sk_test"),
        )

        with self.assertRaises(BillingError) as caught:
            stripe_accounts.start_checkout(self.user, "pro")
        self.assertEqual(caught.exception.status_code, 409)

    def test_checkout_refuses_a_plan_that_is_not_sold(self):
        with self.assertRaises(BillingError):
            self.accounts.start_checkout(self.user, "basic")

    def test_second_checkout_is_refused_so_nobody_is_double_billed(self):
        self.accounts.start_checkout(self.user, "pro")
        with self.assertRaises(BillingError) as caught:
            self.accounts.start_checkout(self.user, "max")
        self.assertEqual(caught.exception.status_code, 409)

    def test_portal_requires_an_existing_billing_account(self):
        with self.assertRaises(BillingError) as caught:
            self.accounts.open_portal(self.user)
        self.assertEqual(caught.exception.status_code, 404)


class WebhookTests(unittest.TestCase):
    """Entitlements move only through verified provider events."""

    class _StubProvider:
        def __init__(self, event):
            self.event = event

        def create_checkout_session(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("not used")

        def create_portal_session(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("not used")

        def parse_webhook_event(self, payload, signature):
            subscription_id = self.event.data.get("stripe_subscription_id") or "sub_stub"
            derived_event_id = (
                f"evt_stub_{subscription_id}_{self.event.kind}_"
                f"{self.event.data.get('status')}_{self.event.data.get('cancel_at')}"
            )
            return SubscriptionEvent(
                kind=self.event.kind,
                event_id=self.event.event_id or derived_event_id,
                user_id=self.event.user_id,
                stripe_customer_id=self.event.stripe_customer_id,
                data={**self.event.data, "stripe_subscription_id": subscription_id},
            )

        def retrieve_subscription(self, stripe_subscription_id):
            event = self.parse_webhook_event(b"", None)
            return ProviderSubscription(
                user_id=event.user_id or "user-1",
                stripe_customer_id=event.stripe_customer_id or "cus_1",
                stripe_subscription_id=stripe_subscription_id,
                plan=event.data.get("plan") or "pro",
                status=event.data.get("status")
                or ("canceled" if event.kind == "deleted" else "active"),
                current_period_end=1_900_000_000,
            )

    def _accounts(self, event):
        self.subscriptions = InMemorySubscriptionRepository()
        return build_test_accounts(
            plans=PLANS,
            subscription_repository=self.subscriptions,
            billing_provider=self._StubProvider(event),
            settings=AccountsSettings(billing_provider="stripe", stripe_secret_key="sk_test"),
        )

    def test_an_unmatched_event_is_acknowledged_without_writing(self):
        accounts = self._accounts(
            SubscriptionEvent(kind="updated", stripe_customer_id="cus_unknown")
        )
        self.assertEqual(accounts.handle_webhook(b"{}", "sig"), "unmatched")

    def test_an_update_grants_the_plan(self):
        accounts = self._accounts(
            SubscriptionEvent(
                kind="updated",
                user_id="user-1",
                stripe_customer_id="cus_1",
                data={"plan": "pro", "status": "active", "stripe_subscription_id": "sub_1"},
            )
        )
        self.assertEqual(accounts.handle_webhook(b"{}", "sig"), "applied")
        self.assertEqual(accounts.describe_subscription("user-1").plan, "pro")

    def test_a_deletion_revokes_the_plan(self):
        subscriptions = InMemorySubscriptionRepository()
        subscriptions.upsert(
            "user-1",
            {
                "plan": "pro",
                "status": "active",
                "stripe_subscription_id": "sub_1",
                "current_period_end": 1_900_000_000,
            },
        )
        accounts = build_test_accounts(
            plans=PLANS,
            subscription_repository=subscriptions,
            billing_provider=self._StubProvider(
                SubscriptionEvent(
                    kind="deleted",
                    user_id="user-1",
                    data={"stripe_subscription_id": "sub_1"},
                )
            ),
            settings=AccountsSettings(billing_provider="stripe", stripe_secret_key="sk_test"),
        )
        self.assertEqual(accounts.handle_webhook(b"{}", "sig"), "applied")
        self.assertEqual(accounts.describe_subscription("user-1").plan, "basic")

    def test_an_event_for_a_stale_subscription_cannot_revoke_the_live_one(self):
        subscriptions = InMemorySubscriptionRepository()
        subscriptions.upsert(
            "user-1",
            {
                "plan": "pro",
                "status": "active",
                "stripe_subscription_id": "sub_live",
                "current_period_end": 1_900_000_000,
            },
        )
        accounts = build_test_accounts(
            plans=PLANS,
            subscription_repository=subscriptions,
            billing_provider=self._StubProvider(
                SubscriptionEvent(
                    kind="deleted",
                    user_id="user-1",
                    data={"stripe_subscription_id": "sub_old"},
                )
            ),
            settings=AccountsSettings(billing_provider="stripe", stripe_secret_key="sk_test"),
        )
        self.assertEqual(accounts.handle_webhook(b"{}", "sig"), "ignored_mismatch")
        self.assertEqual(accounts.describe_subscription("user-1").plan, "pro")


if __name__ == "__main__":
    unittest.main()
