"""Contract tests for the shared `accounts` package.

Deliberately written against the package's own surface, with no Untangle
concepts in sight — the same cases hold in every application that embeds
it, so a copy of this file travels with the package.
"""

import unittest

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
        record = {"plan": "pro", "status": "active"}
        self.assertEqual(resolve_plan_id(record, PLANS), "pro")

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
            return self.event

    def _accounts(self, event):
        self.subscriptions = InMemorySubscriptionRepository()
        return build_test_accounts(
            plans=PLANS,
            subscription_repository=self.subscriptions,
            billing_provider=self._StubProvider(event),
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
            {"plan": "pro", "status": "active", "stripe_subscription_id": "sub_1"},
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
        )
        self.assertEqual(accounts.handle_webhook(b"{}", "sig"), "applied")
        self.assertEqual(accounts.describe_subscription("user-1").plan, "basic")

    def test_an_event_for_a_stale_subscription_cannot_revoke_the_live_one(self):
        subscriptions = InMemorySubscriptionRepository()
        subscriptions.upsert(
            "user-1",
            {"plan": "pro", "status": "active", "stripe_subscription_id": "sub_live"},
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
        )
        self.assertEqual(accounts.handle_webhook(b"{}", "sig"), "ignored_mismatch")
        self.assertEqual(accounts.describe_subscription("user-1").plan, "pro")


if __name__ == "__main__":
    unittest.main()
