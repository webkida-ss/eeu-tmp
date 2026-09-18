"""Local development billing: activates plans instantly, no money involved.

Checkout "succeeds" immediately (the caller applies `activated_plan`), the
portal is a no-op page, and webhooks are never used. Mirrors
MockIdentityProvider: development only, selected via BILLING_PROVIDER=mock.
"""

from __future__ import annotations

from accounts.models import User
from accounts.plans import PlanCatalog
from accounts.ports import BillingError, CheckoutDiscovery, CheckoutSession, SubscriptionEvent


class MockBillingProvider:
    def __init__(self, plans: PlanCatalog | None = None) -> None:
        self._plans = plans or PlanCatalog()

    def create_checkout_session(
        self,
        user: User,
        plan_id: str,
        *,
        success_url: str,
        cancel_url: str,
        stripe_customer_id: str | None = None,
        idempotency_key: str,
        operation_id: str,
    ) -> CheckoutSession:
        if not self._plans.is_paid(plan_id):
            raise BillingError(f"Unknown paid plan: {plan_id}")
        return CheckoutSession(
            url=success_url,
            activated_plan=plan_id,
            stripe_customer_id=stripe_customer_id or f"mock_customer_{user.id}",
            stripe_checkout_session_id=f"mock_checkout_{operation_id}",
        )

    def checkout_price_id(self, plan_id: str) -> str:
        if not self._plans.is_paid(plan_id):
            raise BillingError(f"Unknown paid plan: {plan_id}")
        return f"mock_price_{plan_id}"

    def discover_checkout_sessions(
        self, user: User, *, stripe_customer_id: str | None
    ) -> CheckoutDiscovery:
        # Mock checkout activates locally and has no provider-side history.
        return CheckoutDiscovery(sessions=(), complete=True)

    def create_portal_session(self, stripe_customer_id: str, *, return_url: str) -> str:
        return return_url

    def parse_webhook_event(self, payload: bytes, signature: str | None) -> SubscriptionEvent:
        raise BillingError(
            "Webhooks are not supported by the mock billing provider.", status_code=400
        )
