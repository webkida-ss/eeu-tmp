"""Test doubles for host applications wiring `accounts` into their suites.

Shipped with the package so both applications assemble their fixtures the
same way, and so a change to the container's shape updates every suite at
once.
"""

from __future__ import annotations

from accounts.container import AccountsContainer, build_accounts_container
from accounts.plans import PlanCatalog
from accounts.ports import AuthService, BillingProvider, IdentityProvider, SubscriptionRepository
from accounts.settings import AccountsSettings
from accounts.storage import InMemoryAuthService, InMemorySubscriptionRepository


def build_test_accounts(
    *,
    plans: PlanCatalog | None = None,
    auth_service: AuthService | None = None,
    subscription_repository: SubscriptionRepository | None = None,
    identity_provider: IdentityProvider | None = None,
    billing_provider: BillingProvider | None = None,
    settings: AccountsSettings | None = None,
) -> AccountsContainer:
    """An accounts stack that touches nothing outside the process.

    Defaults to in-memory stores with the mock identity and billing
    providers; pass any port to test against a real one instead.
    """
    plans = plans or PlanCatalog()
    return build_accounts_container(
        settings or AccountsSettings(app_name="Test"),
        plans=plans,
        auth_service=auth_service or InMemoryAuthService(),
        subscription_repository=subscription_repository or InMemorySubscriptionRepository(),
        identity_provider=identity_provider,
        billing_provider=billing_provider,
    )
